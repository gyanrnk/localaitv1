"""
Flask Webhook Server for Gupshup Integration
"""
from datetime import datetime
from flask import Flask, json, request, jsonify
from main import NewsBot
from bulletin_builder import build_bulletin, load_metadata
from video_builder import build_bulletin_video
import logging
import threading
from time import sleep
import tempfile
import os
from config import BASE_DIR 
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
bot = NewsBot()


def process_expired_queue():
    """
    Background worker — runs every 5 seconds.
    1. Expired media WITH caption → process
    2. Expired media WITHOUT caption → already discarded inside get_expired_media()
    3. Expired text (no media arrived) → process as text-only
    """
    while True:
        try:
            sleep(5)

            for item in bot.message_queue.get_expired_media():
                sender     = item['sender']
                media_data = item['media']
                logger.info(f"⏰ Processing expired media+caption for {sender}")

                ext_map   = {'image': '.jpg', 'video': '.mp4', 'audio': '.mp3'}
                ext       = ext_map.get(media_data['type'], '.bin')
                temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
                temp_file.close()

                if bot.gupshup.download_media(media_data['url'], temp_file.name):
                    result = bot.process_message(
                        text=media_data.get('text'),
                        media_path=temp_file.name,
                        sender=sender
                    )
                    if result['success'] and result.get('headline'):
                        bot.gupshup.send_message(
                            sender,
                            f"✅ వార్త ప్రాసెస్ అయింది!\n\n📰 {result['headline']}"
                        )
                os.unlink(temp_file.name)

            for item in bot.message_queue.get_expired_text():
                sender    = item['sender']
                text_data = item['text_data']
                logger.info(f"⏰ Processing expired text-only for {sender}")

                result = bot.process_message(
                    text=text_data.get('text'),
                    media_path=None,
                    sender=sender
                )
                if result['success'] and result.get('headline'):
                    bot.gupshup.send_message(
                        sender,
                        f"✅ వార్త ప్రాసెస్ అయింది!\n\n📰 {result['headline']}"
                    )

        except Exception as e:
            logger.error(f"Background worker error: {e}")
            sleep(5)


# ── Planner state ────────────────────────────────────────────────────────────
_building_lock  = threading.Lock()   # held while a bulletin is being built
_last_count     = 0                  # item count seen at last planner tick


def _get_metadata_count() -> int:
    """Return number of items currently in metadata.json."""
    try:
        return len(load_metadata())
    except Exception:
        return 0


def _run_planner():
    """
    Called when planner decides a build is needed.
    Tries to acquire _building_lock — skips if already building.
    Releases lock after build (success or failure).
    """
    global _last_count

    if not _building_lock.acquire(blocking=False):
        logger.info("🔒 Bulletin build already in progress — skipping this cycle")
        return

    try:
        logger.info("🔨 Building bulletin...")
        bulletin_dir = build_bulletin(5)

        if not bulletin_dir:
            logger.warning("⚠️ No items — bulletin not built")
            return

        logo_path  = os.path.join(BASE_DIR, 'logo.mov')
        intro_path = os.path.join(BASE_DIR, 'intro.mp4')

        video_path = build_bulletin_video(bulletin_dir, logo_path, intro_path)
        if not video_path:
            logger.error("❌ Video build failed")
            return

        # Snapshot count AFTER successful build so next cycle
        # only triggers if new items arrived since this build.
        _last_count = _get_metadata_count()
        logger.info(f"✅ Bulletin ready → {video_path}  (item count snapshot: {_last_count})")

    except Exception as e:
        logger.error(f"❌ Planner build error: {e}")

    finally:
        _building_lock.release()


def planner_loop():
    """
    Runs every 5 minutes.
    Builds a bulletin only when new items have arrived since the last build.

    Logic:
      current_count == last_count  → nothing new, skip
      current_count  > last_count  → new items exist, try to build
      _building_lock held          → previous build still running, skip
    """
    global _last_count

    # Initialise snapshot so first cycle doesn't build on stale data
    _last_count = _get_metadata_count()
    logger.info(f"⏰ Planner started (current item count: {_last_count})")

    while True:
        sleep(300)   # wait 5 minutes

        try:
            current_count = _get_metadata_count()

            if current_count == _last_count:
                logger.info(
                    f"⏭️  Planner: no new items since last build "
                    f"(count={current_count}) — skipping"
                )
                continue

            # New items arrived
            logger.info(
                f"🆕 Planner: {current_count - _last_count} new item(s) detected "
                f"({_last_count} → {current_count}) — triggering build"
            )
            threading.Thread(target=_run_planner, daemon=True).start()

        except Exception as e:
            logger.error(f"❌ Planner loop error: {e}")


# ── Start background threads ─────────────────────────────────────────────────
threading.Thread(target=planner_loop,          daemon=True).start()
logger.info("⏰ Planner loop started (5-min interval, builds only when new items arrive)")

threading.Thread(target=process_expired_queue, daemon=True).start()
logger.info("🚀 Background worker started")


# ── Routes ───────────────────────────────────────────────────────────────────
@app.route('/', methods=['GET', 'POST'])
@app.route('/webhook', methods=['GET', 'POST'])
@app.route('/gupshup/webhook', methods=['GET', 'POST'])
def webhook():
    try:
        if 'application/json' in request.content_type:
            webhook_data = request.json
        else:
            webhook_data = request.get_json(force=True)

        if webhook_data.get('type') == 'user-event':
            payload = webhook_data.get('payload', {})
            if payload.get('type') == 'sandbox-start':
                logger.info("✅ Sandbox webhook acknowledged")
                return jsonify({'status': 'success'}), 200

        if webhook_data.get('type') not in ['message-event', 'user-event', 'message']:
            return jsonify({'status': 'acknowledged'}), 200

        result = bot.process_gupshup_webhook(webhook_data)

        if result.get('waiting'):
            logger.info("⏳ Waiting for matching message...")
            return jsonify({'status': 'waiting'}), 200

        if result.get('duplicate'):
            logger.info("⭕ Duplicate, skipping")
            return jsonify({'status': 'duplicate'}), 200

        if result.get('success'):
            sender = result.get('sender')
            if sender and result.get('headline'):
                bot.gupshup.send_message(
                    sender,
                    f"✅ వార్త ప్రాసెస్ అయింది!\n\n📰 {result['headline']}"
                )
            logger.info("✅ Success")
            return jsonify({'status': 'success', 'headline': result.get('headline')}), 200

        if webhook_data.get('type') == 'user-event':
            return jsonify({'status': 'success'}), 200

        logger.error(f"❌ Failed: {result.get('error')}")
        return jsonify({'status': 'error', 'error': result.get('error')}), 400

    except Exception as e:
        logger.error(f"❌ Error: {e}")
        logger.exception("Full traceback:")
        return jsonify({'status': 'error', 'error': str(e)}), 500


@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'healthy'}), 200


if __name__ == '__main__':
    from config import PORT
    app.run(host='0.0.0.0', port=PORT, debug=False)



