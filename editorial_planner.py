import json
import re
from config import EDITORIAL_PLANNER_PROMPT, WORDS_PER_SECOND_TTS


# ── Timing constants (must match config.py budget) ────────────────────────────
MAX_INTRO_WORDS    = round(15 * WORDS_PER_SECOND_TTS)   # ~33 words  (~15s)
MAX_ANALYSIS_WORDS = round(16 * WORDS_PER_SECOND_TTS)   # ~35 words  (~16s)
MIN_CLIP_DUR       = 8.0    # seconds
MAX_CLIP_DUR       = 20.0   # seconds
HARD_TOTAL_CAP     = 59.0   # seconds


class EditorialPlanner:
    def __init__(self, llm_client):
        self.llm = llm_client

    # ──────────────────────────────────────────────────────────────────────────
    def build_story_plan(self, transcript_segments, user_text: str = ''):
        if not transcript_segments:
            return self._fallback_plan()

        transcript_text = self._format_transcript(transcript_segments)

        if user_text and user_text.strip():
            combined_input = (
                f"NEWS CONTENT (use this as PRIMARY source for tts_intro and tts_analysis):\n"
                f"{user_text.strip()}\n\n"
                f"VIDEO TRANSCRIPT (use ONLY for clip selection — timestamps ke liye):\n"
                f"{transcript_text}"
            )
        else:
            combined_input = transcript_text

        response = self.llm.generate_editorial_plan(combined_input)

        raw = response.strip() if response else ""
        if not raw:
            return self._fallback_plan()

        if raw.startswith("```"):
            raw = re.sub(r"^```[a-z]*\n?", "", raw).rstrip("`").strip()

        try:
            plan = json.loads(raw)
        except json.JSONDecodeError:
            return self._fallback_plan()

        return self._validate_and_enforce(plan, transcript_segments)
    # ──────────────────────────────────────────────────────────────────────────
    def _format_transcript(self, segments):
        return "\n".join(
            f"[{s['start']:.2f} - {s['end']:.2f}] {s['text']}"
            for s in segments
        )

    # ──────────────────────────────────────────────────────────────────────────
    def _validate_and_enforce(self, plan, transcript_segments):
        try:
            structure = plan.get("structure", "intro_clip_analysis")
            clip      = plan.get("clip") or {}
            intro     = plan.get("tts_intro",    "").strip()
            analysis  = plan.get("tts_analysis", "").strip()

            # ── Structure whitelist ───────────────────────────────────────────
            if structure not in ("intro_clip_analysis", "clip_intro_analysis", "intro_analysis_clip"):
                structure = "intro_clip_analysis"

            # ── Clip timing ───────────────────────────────────────────────────
            start = float(clip.get("start", 0))
            end   = float(clip.get("end",   0))
            score = float(clip.get("score", 0))
            text  = clip.get("text", "")

            clip_dur = end - start

            # Reject completely invalid clip
            if start < 0 or end <= start:
                return self._fallback_plan()

            # Enforce 8–20s clip window
            if clip_dur < MIN_CLIP_DUR:
                end      = start + MIN_CLIP_DUR
                clip_dur = MIN_CLIP_DUR
            elif clip_dur > MAX_CLIP_DUR:
                end      = start + MAX_CLIP_DUR
                clip_dur = MAX_CLIP_DUR

            # ── Sentence-completeness helper ──────────────────────────────────
            def _ensure_complete(t: str) -> str:
                t = t.strip()
                if not t:
                    return t
                if t[-1] not in ".!?।":
                    for punct in (".", "!", "?", "।"):
                        last = t.rfind(punct)
                        if last > len(t) // 2:
                            return t[:last + 1].strip()
                return t

            # ── Word-count hard trim (at sentence boundary) ───────────────────
            def _trim_to_words(t: str, max_words: int) -> str:
                words = t.strip().split()
                if len(words) <= max_words:
                    return t.strip()
                truncated = " ".join(words[:max_words])
                last_sent = max(
                    (m.end() for m in re.finditer(r"[.!?।]\s*", truncated)),
                    default=len(truncated)
                )
                return truncated[:last_sent].strip() or truncated

            intro    = _ensure_complete(intro)
            analysis = _ensure_complete(analysis)
            intro    = _trim_to_words(intro,    MAX_INTRO_WORDS)
            analysis = _trim_to_words(analysis, MAX_ANALYSIS_WORDS)

            # ── Minimum content check ─────────────────────────────────────────
            if not intro or len(intro.split()) < 8:
                return self._fallback_plan()
            if not analysis or len(analysis.split()) < 5:
                return self._fallback_plan()

            # ── 59-second total budget check ──────────────────────────────────
            intro_dur    = len(intro.split())    / WORDS_PER_SECOND_TTS
            analysis_dur = len(analysis.split()) / WORDS_PER_SECOND_TTS
            total_est    = intro_dur + clip_dur + analysis_dur

            print(f"   ⏱️  Budget: intro={intro_dur:.1f}s + clip={clip_dur:.1f}s "
                  f"+ analysis={analysis_dur:.1f}s = {total_est:.1f}s")

            if total_est > HARD_TOTAL_CAP:
                # First try: shrink clip
                allowed_clip = max(MIN_CLIP_DUR, HARD_TOTAL_CAP - intro_dur - analysis_dur)
                allowed_clip = min(allowed_clip, MAX_CLIP_DUR)
                end      = start + allowed_clip
                clip_dur = allowed_clip
                total_est = intro_dur + clip_dur + analysis_dur
                print(f"   ✂️  Clip trimmed → {clip_dur:.1f}s | new total={total_est:.1f}s")

            if total_est > HARD_TOTAL_CAP:
                # Second try: trim analysis further
                budget_for_analysis = HARD_TOTAL_CAP - intro_dur - clip_dur
                max_analysis_words  = max(5, int(budget_for_analysis * WORDS_PER_SECOND_TTS))
                analysis  = _trim_to_words(analysis, max_analysis_words)
                analysis  = _ensure_complete(analysis)
                total_est = intro_dur + clip_dur + len(analysis.split()) / WORDS_PER_SECOND_TTS
                print(f"   ✂️  Analysis trimmed | new total={total_est:.1f}s")

            print(f"   ✅ Final plan: structure={structure} | "
                  f"clip=[{start:.1f}s→{end:.1f}s] | "
                  f"intro={len(intro.split())}w | analysis={len(analysis.split())}w")

            return {
                "structure":    structure,
                "clip": {
                    "start": round(start, 2),
                    "end":   round(end,   2),
                    "text":  text,
                    "score": round(score, 2),
                },
                "tts_intro":    intro,
                "tts_analysis": analysis,
            }

        except Exception as e:
            print(f"   ⚠️  _validate_and_enforce error: {e}")
            return self._fallback_plan()

    # ──────────────────────────────────────────────────────────────────────────
    def _fallback_plan(self):
        return {
            "structure":    "intro_clip_analysis",
            "clip":         None,
            "tts_intro":    "ఈ వార్తకు సంబంధించిన వివరాలు అందుతున్నాయి.",
            "tts_analysis": "మరిన్ని వివరాలు త్వరలో వెల్లడి అవుతాయని తెలుస్తోంది.",
        }