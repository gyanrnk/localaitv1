
import re
from typing import Dict, Optional, List, Tuple


def _score_segment_text(text: str) -> float:
    score = 0.0
    words = text.strip().split()

    if text.strip().endswith(('.', '!', '?')):
        score += 2.0
    first = ' '.join(words[:3]).lower()
    weak  = ['so', 'but', 'and', 'because', 'as i', 'like i']
    score += -1.5 if any(first.startswith(w) for w in weak) else 2.0
    strong_verbs = ['announce', 'declare', 'confirm', 'reveal', 'state', 'promise', 'deny', 'accuse']
    if any(v in text.lower() for v in strong_verbs):
        score += 1.5
    emotional = ['shocking', 'unprecedented', 'historic', 'urgent', 'critical', 'breaking']
    if any(m in text.lower() for m in emotional):
        score += 1.0
    if '"' in text or "'" in text:
        score += 0.5
    if 10 <= len(words) <= 35:
        score += 1.0
    return score


def find_best_clip(transcript: str, segments: list = None,
                   target_duration: Tuple[float, float] = (10.0, 30.0)) -> Optional[Dict]:

    min_dur, max_dur = target_duration

    # ── Real segments from Whisper ────────────────────────────────────────────
    if segments:
        best       = None
        best_score = -1

        for i, seg in enumerate(segments):
            seg_dur = seg['end'] - seg['start']

            # Single segment fits target duration
            if min_dur <= seg_dur <= max_dur:
                score = _score_segment_text(seg['text'])
                if score > best_score:
                    best_score = score
                    best = {'text': seg['text'], 'start': seg['start'], 'end': seg['end']}

            # Combine consecutive segments to reach min_dur
            elif seg_dur < min_dur:
                combined_text = seg['text']
                end_time      = seg['end']
                for j in range(i + 1, len(segments)):
                    combined_text += ' ' + segments[j]['text']
                    end_time       = segments[j]['end']
                    combo_dur      = end_time - seg['start']
                    if combo_dur >= min_dur:
                        score = _score_segment_text(combined_text)
                        if score > best_score:
                            best_score = score
                            best = {
                                'text':  combined_text,
                                'start': seg['start'],
                                'end':   end_time
                            }
                        break
                    if combo_dur > max_dur:
                        break

        if best:
            # Enforce minimum 10 sec — expand end if needed
            if (best['end'] - best['start']) < min_dur:
                best['end'] = min(best['start'] + min_dur,
                                  segments[-1]['end'])
            return best

        # No segment scored well — just take the middle min_dur seconds
        total_start = segments[0]['start']
        total_end   = segments[-1]['end']
        mid         = (total_start + total_end) / 2
        clip_s      = max(total_start, mid - min_dur / 2)
        clip_e      = min(total_end,   clip_s + min_dur)
        mid_text    = ' '.join(s['text'] for s in segments
                               if s['start'] >= clip_s and s['end'] <= clip_e + 1)
        return {'text': mid_text or segments[0]['text'],
                'start': round(clip_s, 2), 'end': round(clip_e, 2)}

    # ── Fallback: heuristic from plain transcript (no segments available) ─────
    # Estimate ~2.5 words per second for natural speech
    words = transcript.strip().split()
    if not words:
        return None

    total_words    = len(words)
    words_per_sec  = 2.5
    total_duration = total_words / words_per_sec

    # If total video is shorter than min_dur, use the whole thing
    if total_duration <= min_dur:
        return {
            'text':  transcript.strip(),
            'start': 0.0,
            'end':   total_duration
        }

    # Pick best sentence cluster that covers at least min_dur seconds
    sentences = re.split(r'[.!?]+', transcript)
    sentences = [s.strip() for s in sentences if len(s.strip()) > 5]
    if not sentences:
        # No sentences — just take middle chunk of min_dur length
        mid_word     = total_words // 2
        half_clip    = int((min_dur * words_per_sec) / 2)
        start_word   = max(0, mid_word - half_clip)
        end_word     = min(total_words, mid_word + half_clip)
        start_time   = start_word / words_per_sec
        end_time     = end_word / words_per_sec
        return {
            'text':  ' '.join(words[start_word:end_word]),
            'start': round(start_time, 2),
            'end':   round(end_time, 2)
        }

    # Score each sentence and pick best, then expand to hit min_dur
    scored = []
    word_offset = 0
    for sent in sentences:
        sent_words = sent.split()
        start_t    = word_offset / words_per_sec
        end_t      = (word_offset + len(sent_words)) / words_per_sec
        scored.append((start_t, end_t, sent, _score_segment_text(sent)))
        word_offset += len(sent_words)

    best_idx   = max(range(len(scored)), key=lambda i: scored[i][3])
    s_start, s_end, s_text, _ = scored[best_idx]

    # Expand forward/backward until we hit min_dur
    clip_start = s_start
    clip_end   = s_end
    clip_text  = s_text
    lo, hi     = best_idx - 1, best_idx + 1

    while (clip_end - clip_start) < min_dur:
        expanded = False
        if hi < len(scored):
            clip_end  = scored[hi][1]
            clip_text = clip_text + ' ' + scored[hi][2]
            hi += 1
            expanded = True
        if (clip_end - clip_start) < min_dur and lo >= 0:
            clip_start = scored[lo][0]
            clip_text  = scored[lo][2] + ' ' + clip_text
            lo -= 1
            expanded = True
        if not expanded:
            break  # no more sentences to add

    # Cap at max_dur
    if (clip_end - clip_start) > max_dur:
        clip_end = clip_start + max_dur

    return {
        'text':  clip_text.strip(),
        'start': round(clip_start, 2),
        'end':   round(clip_end, 2)
    }


def analyze_clip_for_structure(transcript: str, clip_text: str,
                                clip_start: float, clip_end: float) -> Dict:
    score     = _score_segment_text(clip_text)
    score     = max(0, min(10, score))
    reasoning = []

    clip_words = clip_text.strip().split()
    if clip_text.strip().endswith(('.', '!', '?')):
        reasoning.append("Complete sentence")
    first = ' '.join(clip_words[:3]).lower()
    weak  = ['so', 'but', 'and', 'because', 'as i', 'like i']
    reasoning.append("Weak/contextual start" if any(first.startswith(w) for w in weak) else "Strong independent start")
    strong_verbs = ['announce', 'declare', 'confirm', 'reveal', 'state', 'promise', 'deny', 'accuse']
    if any(v in clip_text.lower() for v in strong_verbs):
        reasoning.append("Strong declarative statement")
    emotional = ['shocking', 'unprecedented', 'historic', 'urgent', 'critical', 'breaking']
    if any(m in clip_text.lower() for m in emotional):
        reasoning.append("High emotional weight")
    if '"' in clip_text or "'" in clip_text:
        reasoning.append("Contains quoted speech")

    if score >= 7.0:
        structure             = 'clip_first'
        structure_reasoning   = "High-impact clip, lead with it"
    elif score >= 4.0:
        structure             = 'standard'
        structure_reasoning   = "Balanced clip, use standard intro→clip→analysis"
    else:
        structure             = 'narrative'
        structure_reasoning   = "Weak clip, build context first then reveal"

    return {
        'structure':           structure,
        'score':               round(score, 1),
        'reasoning':           ' | '.join(reasoning),
        'structure_reasoning': structure_reasoning,
        'clip_info': {
            'text':       clip_text,
            'start':      clip_start,
            'end':        clip_end,
            'duration':   clip_end - clip_start,
            'word_count': len(clip_words)
        }
    }


def get_structure_decision(transcript: str, existing_clip: Optional[Dict] = None,
                            segments: list = None) -> Dict:
    try:
        if not existing_clip:
            existing_clip = find_best_clip(transcript, segments=segments)

        if not existing_clip:
            return {
                'structure':           'standard',
                'score':               0,
                'reasoning':           'No suitable clip found',
                'structure_reasoning': 'Default to standard structure',
                'clip_info':           None
            }

        return analyze_clip_for_structure(
            transcript=transcript,
            clip_text=existing_clip['text'],
            clip_start=existing_clip.get('start', 0),
            clip_end=existing_clip.get('end', 0)
        )

    except Exception as e:
        print(f"⚠️ Clip analysis error: {e}")
        return {
            'structure':           'standard',
            'score':               0,
            'reasoning':           f'Analysis failed: {str(e)}',
            'structure_reasoning': 'Fallback to standard structure',
            'clip_info':           existing_clip
        }


CLIP_FIRST_THRESHOLD = 7.5

def should_use_clip_first(analysis_result: Dict) -> bool:
    return (
        analysis_result['structure'] == 'clip_first' and
        analysis_result['score'] >= CLIP_FIRST_THRESHOLD
    )