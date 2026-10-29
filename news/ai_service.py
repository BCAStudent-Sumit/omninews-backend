import os
import re
import json
import logging
import urllib.request
import urllib.parse
from html import unescape
import concurrent.futures
from django.conf import settings

logger = logging.getLogger(__name__)

try:
    from google import genai
    from google.genai import types
    HAS_GENAI_LIB = True
except Exception:
    HAS_GENAI_LIB = False

_TRANSLATION_CACHE = {}
_AI_ASSISTANCE_CACHE = {}

# Mapping from standard language codes to TTS and display metadata
LANGUAGE_CONFIG = {
    'en': {
        'name': 'English',
        'locale': 'en-US',
        'greeting': 'Hello, here is your OmniNews AI briefing.',
        'headline_intro': "Today's top story:",
        'body_intro': 'Reporting details indicate that',
        'signoff': 'Stay tuned with OmniNews for verified updates. Thank you.',
    },
    'en_in': {
        'name': 'English (India)',
        'locale': 'en-IN',
        'greeting': 'Hello, here is your OmniNews India AI briefing.',
        'headline_intro': "Top national & regional dispatch:",
        'body_intro': 'In detail,',
        'signoff': 'Stay tuned with OmniNews for live verified coverage. Thank you.',
    },
    'bn': {
        'name': 'Bengali (বাংলা)',
        'locale': 'bn-IN',
        'greeting': 'নমস্কার। ওমনিনিউজ এআই সংবাদ বুলেটিনে আপনাকে স্বাগত।',
        'headline_intro': 'আজকের প্রধান খবর:',
        'body_intro': 'বিস্তারিত প্রতিবেদনে জানা গেছে,',
        'signoff': 'খবরের নির্ভরযোগ্য ও তাৎক্ষণিক আপডেটের জন্য ওমনিনিউজের সঙ্গেই থাকুন। ধন্যবাদ।',
    },
    'bn_in': {
        'name': 'Bengali (West Bengal / India)',
        'locale': 'bn-IN',
        'greeting': 'নমস্কার। ওমনিনিউজ এআই বিশেষ সংবাদে আপনাকে স্বাগত।',
        'headline_intro': 'আজকের প্রধান খবর:',
        'body_intro': 'প্রতিবেদন অনুযায়ী,',
        'signoff': 'সত্য ও তথ্যনিষ্ঠ খবরের জন্য ওমনিনিউজ সঙ্গে রাখুন। ধন্যবাদ।',
    },
    'bn_bd': {
        'name': 'Bengali (Bangladesh)',
        'locale': 'bn-BD',
        'greeting': 'আসসালামু আলাইকুম ও শুভেচ্ছা। ওমনিনিউজ এআই সংবাদ বুলেটিনে আপনাকে স্বাগতম।',
        'headline_intro': 'আজকের শীর্ষ সংবাদ:',
        'body_intro': 'প্রতিবেদনে জানা গেছে,',
        'signoff': 'সর্বশেষ তথ্যের জন্য ওমনিনিউজ সঙ্গেই রাখুন। ধন্যবাদ।',
    },
    'hi': {
        'name': 'Hindi (हिंदी)',
        'locale': 'hi-IN',
        'greeting': 'नमस्ते, यह आपका ओमनीन्यूज़ एআই बुलेटिन है।',
        'headline_intro': 'आज की मुख्य खबर:',
        'body_intro': 'विस्तृत रिपोर्ट के अनुसार,',
        'signoff': 'ताज़ा और सटीक खबरों के लिए ओमनीन्यूज़ देखते रहें। धन्यवाद।',
    },
    'mr': {'name': 'Marathi', 'locale': 'mr-IN', 'greeting': 'नमस्कार, हे तुमचे ऑम्नीन्यूज एआय बुलेटिन आहे.'},
    'te': {'name': 'Telugu', 'locale': 'te-IN', 'greeting': 'నమస్కారం, ఇది మీ ఓమ్నిన్యూస్ AI వార్తా సారాంశం.'},
    'ta': {'name': 'Tamil', 'locale': 'ta-IN', 'greeting': 'வணக்கம், இது உங்கள் ஆம்னிநியூஸ் AI செய்தி தொகுப்பு.'},
    'gu': {'name': 'Gujarati', 'locale': 'gu-IN', 'greeting': 'નમસ્તે, આ તમારું ઓમ્નીન્યૂઝ એઆઈ બુલેટિન છે.'},
    'ur': {'name': 'Urdu', 'locale': 'ur-IN', 'greeting': 'السلام علیکم، یہ آپ کا اومنی نیوز اے آئی بلیٹن ہے۔'},
    'kn': {'name': 'Kannada', 'locale': 'kn-IN', 'greeting': 'ನಮಸ್ಕಾರ, ಇದು ನಿಮ್ಮ ಓಮ್ನಿನಿವ್ಸ್ AI ಬುಲೆಟಿನ್.'},
    'ml': {'name': 'Malayalam', 'locale': 'ml-IN', 'greeting': 'നമസ്കാരം, ഇതാണ് നിങ്ങളുടെ ഓംനിന്യൂസ് AI ബുള്ളറ്റിൻ.'},
    'pa': {'name': 'Punjabi', 'locale': 'pa-IN', 'greeting': 'ਸਤਿ ਸ੍ਰੀ ਅਕਾਲ, ਇਹ ਤੁਹਾਡਾ ਓਮਨੀਨਿਊਜ਼ ਏਆਈ ਬੁਲੇਟਿਨ ਹੈ।'},
    'es': {'name': 'Spanish', 'locale': 'es-ES', 'greeting': 'Hola, este es su boletín informativo OmniNews AI.'},
    'fr': {'name': 'French', 'locale': 'fr-FR', 'greeting': 'Bonjour, voici votre bulletin d\'information OmniNews AI.'},
    'de': {'name': 'German', 'locale': 'de-DE', 'greeting': 'Guten Tag, hier ist Ihr OmniNews KI-Nachrichtenüberblick.'},
    'ja': {'name': 'Japanese', 'locale': 'ja-JP', 'greeting': 'こんにちは、OmniNews AIニュースブリーフィングです。'},
    'ar': {'name': 'Arabic', 'locale': 'ar-SA', 'greeting': 'مرحباً، إليكم موجز أومني نيوز للذكاء الاصطناعي.'},
    'ru': {'name': 'Russian', 'locale': 'ru-RU', 'greeting': 'Здравствуйте, это ваш выпуск новостей OmniNews AI.'},
    'zh': {'name': 'Chinese', 'locale': 'zh-CN', 'greeting': '您好，这是您的 OmniNews AI 新闻简报。'},
    'pt': {'name': 'Portuguese', 'locale': 'pt-PT', 'greeting': 'Olá, este é o seu boletim de notícias OmniNews AI.'},
    'ko': {'name': 'Korean', 'locale': 'ko-KR', 'greeting': '안녕하세요, 옴니뉴스 AI 뉴스 브리핑입니다.'},
}

# Specialized phonetic mappings for Bengali news TTS pronunciation
BENGALI_ACRONYMS = {
    r'\bISRO\b': 'ইসরো',
    r'\bNASA\b': 'নাসা',
    r'\bAI\b': 'এআই',
    r'\bPM\b': 'প্রধানমন্ত্রী',
    r'\bCM\b': 'মুখ্যমন্ত্রী',
    r'\bIPL\b': 'আইপিএল',
    r'\bBCCI\b': 'বিসিসিআই',
    r'\bICC\b': 'আইসিসি',
    r'\bUN\b': 'জাতিসংঘ',
    r'\bUNO\b': 'জাতিসংঘ',
    r'\bWHO\b': 'বিশ্ব স্বাস্থ্য সংস্থা',
    r'\bRBI\b': 'আরবিআই',
    r'\bBJP\b': 'বিজেপি',
    r'\bTMC\b': 'তৃণমূল কংগ্রেস',
    r'\bCPIM\b': 'সিপিআইএম',
    r'\bUSA\b': 'যুক্তরাষ্ট্র',
    r'\bUS\b': 'মার্কিন যুক্তরাষ্ট্র',
    r'\bUK\b': 'যুক্তরাজ্য',
    r'\bEU\b': 'ইউরোপীয় ইউনিয়ন',
    r'\bCOVID\b': 'কোভিড',
    r'\bCOVID-19\b': 'কোভিড-১৯',
    r'\bCEO\b': 'সিইও',
    r'\bGDP\b': 'জিডিপি',
    r'\bIT\b': 'আইটি',
    r'\bDr\b\.?': 'ডক্টর',
    r'\bProf\b\.?': 'অধ্যাপক',
    r'\bvs\b\.?': 'বনাম',
    r'\bPTI\b': 'পিটিআই',
    r'\bANI\b': 'এএনআই',
}

BENGALI_LATIN_DIGITS = {
    '0': '০', '1': '১', '2': '২', '3': '৩', '4': '৪',
    '5': '৫', '6': '৬', '7': '৭', '8': '৮', '9': '৯'
}


def clean_html(text: str) -> str:
    """Removes HTML markup and cleans excessive whitespace."""
    if not text:
        return ""
    text = unescape(text)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def clean_bengali_text_for_speech(text: str) -> str:
    """
    Rhythm & phonetic optimizer for Bengali text-to-speech.
    Converts English acronyms to Bengali script, converts numerals, replaces periods
    with Bengali Dari (।), and inserts natural breath pauses for speech synthesis.
    """
    if not text:
        return ""

    # Replace English acronyms with Bengali phonetic equivalents
    for pat, rep in BENGALI_ACRONYMS.items():
        text = re.sub(pat, rep, text, flags=re.IGNORECASE)

    # Convert Latin numerals into Bengali numerals
    text = re.sub(r'\b\d+\b', lambda m: ''.join(BENGALI_LATIN_DIGITS.get(d, d) for d in m.group(0)), text)

    # Convert English periods to Bengali Dari '।'
    text = re.sub(r'\.\s*', '। ', text)

    # Ensure clean spacing after punctuation
    text = re.sub(r'([।,?])(?=[^\s])', r'\1 ', text)

    # Clean multiple consecutive daris
    text = re.sub(r'।\s*।+', '।', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def translate_text(text: str, target_lang: str) -> str:
    """
    Translates text to target language code using reliable translation endpoint.
    Auto-detects source language (sl=auto) and translates to any target language.
    Falls back to original text on network timeout.
    """
    if not text or not text.strip():
        return text

    # Extract base 2-letter language code if locale supplied (e.g. 'bn-IN' -> 'bn')
    tl = target_lang.split('-')[0].split('_')[0].lower()
    cleaned = text.strip()
    cache_key = (cleaned, tl)
    if cache_key in _TRANSLATION_CACHE:
        return _TRANSLATION_CACHE[cache_key]

    # Limit chunk size to prevent request url overflow
    text_to_translate = cleaned[:2000]

    try:
        encoded = urllib.parse.quote(text_to_translate)
        url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl={tl}&dt=t&q={encoded}"
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0"}
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
            if payload and isinstance(payload, list) and len(payload) > 0 and isinstance(payload[0], list):
                translated_parts = [segment[0] for segment in payload[0] if segment and len(segment) > 0 and segment[0]]
                res = "".join(translated_parts)
                if res and res.strip():
                    _TRANSLATION_CACHE[cache_key] = res
                    return res
    except Exception:
        pass
    return text


def translate_full_article(text: str, target_lang: str) -> str:
    """
    Translates full article text preserving paragraph structures and sentence flow.
    Splits long bodies across paragraphs and stitches them with proper punctuation.
    """
    if not text or not text.strip():
        return text

    tl = target_lang.split('-')[0].split('_')[0].lower()
    paragraphs = text.split("\n")
    translated_paras = []

    for p in paragraphs:
        cleaned_p = p.strip()
        if not cleaned_p:
            translated_paras.append("")
            continue
        if len(cleaned_p) > 1200:
            sentences = re.split(r'(?<=[.!?।])\s+', cleaned_p)
            trans_sentences = [translate_text(s, tl) for s in sentences if s.strip()]
            translated_paras.append(" ".join(trans_sentences))
        else:
            translated_paras.append(translate_text(cleaned_p, tl))

    res = "\n".join(translated_paras)
    if tl == 'bn':
        res = clean_bengali_text_for_speech(res)
    return res


def translate_batch(texts: list, target_lang: str) -> list:
    """
    Translates multiple strings in parallel using a thread pool.
    Results are cached to minimize redundant network round trips.
    """
    if not texts:
        return list(texts)

    tl = target_lang.split('-')[0].split('_')[0].lower()
    results = [None] * len(texts)
    to_fetch = []

    for idx, t in enumerate(texts):
        key = (t.strip() if t else "", tl)
        if key in _TRANSLATION_CACHE:
            results[idx] = _TRANSLATION_CACHE[key]
        else:
            to_fetch.append((idx, t))

    if not to_fetch:
        return results

    def _worker(item):
        idx, original = item
        trans = translate_text(original, tl)
        return idx, trans

    max_w = min(len(to_fetch), 12)
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_w) as executor:
        for idx, trans in executor.map(_worker, to_fetch):
            results[idx] = trans

    return results


def extract_key_sentences(text: str, max_sentences: int = 4) -> list:
    """Extracts top informative sentences based on length and relevance."""
    raw_sentences = re.split(r'(?<=[.!?])\s+', text)
    valid_sentences = [
        s.strip() for s in raw_sentences
        if len(s.strip()) > 30 and not s.strip().startswith(('Click', 'Read', 'Subscribe', 'Photo:', 'Follow us'))
    ]

    if not valid_sentences:
        valid_sentences = [s.strip() for s in raw_sentences if s.strip()]

    return valid_sentences[:max_sentences]


def answer_question_from_context(question: str, title: str, body: str, target_lang: str) -> str:
    """Answers a user question contextually from the article body with natural language framing."""
    q_lower = question.lower()
    sentences = re.split(r'(?<=[.!?])\s+', body)

    # Keywords from question
    q_words = [w for w in re.findall(r'\b[a-zA-Z0-9]{3,}\b', q_lower) if w not in ('what', 'when', 'where', 'which', 'who', 'how', 'why', 'this', 'that', 'with', 'from')]

    best_match = None
    best_score = 0

    for s in sentences:
        s_clean = s.strip()
        if len(s_clean) < 20:
            continue
        score = sum(1 for w in q_words if w in s_clean.lower())
        if score > best_score:
            best_score = score
            best_match = s_clean

    if best_match and best_score > 0:
        ans_en = best_match
    else:
        first_s = sentences[0].strip() if sentences else title
        ans_en = first_s

    if target_lang.startswith('bn'):
        # Bengali enhanced Q&A framing
        translated_ans = clean_bengali_text_for_speech(translate_text(ans_en, 'bn'))
        return f"ওমনিনিউজের বিশেষ প্রতিবেদন অনুসারে: {translated_ans}"
    elif target_lang not in ('en', 'en_in'):
        translated_ans = translate_text(ans_en, target_lang)
        return translated_ans

    return f"Based on the verified reporting: {ans_en}"


def get_gemini_api_key(passed_key: str = None) -> str:
    """Returns the active Gemini API key from parameter, Django settings, or environment."""
    if passed_key and passed_key.strip():
        return passed_key.strip()
    key = getattr(settings, "GEMINI_API_KEY", "") or os.environ.get("GEMINI_API_KEY", "") or os.environ.get("GOOGLE_API_KEY", "")
    return (key or "").strip()


def get_gemini_model(passed_model: str = None) -> str:
    """Returns the configured Gemini model name."""
    if passed_model and passed_model.strip():
        return passed_model.strip()
    return getattr(settings, "GEMINI_MODEL", "") or os.environ.get("GEMINI_MODEL", "gemini-3-flash-preview")


def get_gemini_status() -> dict:
    """Returns real-time status of the Gemini AI integration."""
    key = get_gemini_api_key()
    has_key = bool(key and len(key) >= 10)
    masked_key = f"{key[:4]}...{key[-4:]}" if has_key else ""
    model = get_gemini_model()
    return {
        "has_gemini_key": has_key,
        "masked_key": masked_key,
        "model": model,
        "provider": f"Google Gemini ({model})" if has_key else "OmniAI Neural Engine",
        "supported_models": [
            "gemini-3-flash-preview",
            "gemini-2.5-flash",
            "gemini-flash-latest",
        ],
        "status": "ready" if has_key else "fallback_active",
        "sdk_available": HAS_GENAI_LIB,
    }


def _update_env_file(key: str, value: str):
    """Safely updates or appends a key-value pair in .env."""
    try:
        base_dir = getattr(settings, "BASE_DIR", None)
        if not base_dir:
            return
        file_path = os.path.join(base_dir, ".env")
        lines = []
        if os.path.exists(file_path):
            with open(file_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
        found = False
        new_lines = []
        for line in lines:
            if line.startswith(f"{key}="):
                new_lines.append(f"{key}={value}\n")
                found = True
            else:
                new_lines.append(line)
        if not found:
            new_lines.append(f"{key}={value}\n")
        with open(file_path, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
    except Exception as e:
        logger.warning(f"Failed to update .env: {e}")


def _call_gemini_rest(prompt: str, system_instruction: str, api_key: str, model: str) -> str:
    """Zero-dependency direct REST fallback to Gemini API."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.2,
            "responseMimeType": "application/json"
        }
    }
    if system_instruction:
        payload["systemInstruction"] = {"parts": [{"text": system_instruction}]}
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=25) as resp:
        result = json.loads(resp.read().decode("utf-8"))
        candidates = result.get("candidates", [])
        if candidates:
            parts = candidates[0].get("content", {}).get("parts", [])
            if parts:
                return parts[0].get("text", "")
    return None


def test_gemini_key(api_key: str, model: str = None) -> dict:
    """
    Validates a Google Gemini API key.
    Tests the requested model and automatically tries candidate models if the chosen one returns 404/NOT_FOUND.
    """
    if not api_key or len(api_key.strip()) < 10:
        return {"success": False, "error": "API key appears too short or invalid."}
    key = api_key.strip()

    requested_model = (model or get_gemini_model()).strip()
    candidates = [
        requested_model,
        "gemini-flash-lite-latest",
        "gemini-3.5-flash-lite",
        "gemini-3.1-flash-lite",
        "gemini-flash-latest",
    ]
    # Deduplicate while preserving order
    seen = set()
    models_to_try = [m for m in candidates if not (m in seen or seen.add(m))]

    last_error = None

    if HAS_GENAI_LIB:
        try:
            http_opts = types.HttpOptions(timeout=10000) if hasattr(types, "HttpOptions") else None
            client = genai.Client(api_key=key, http_options=http_opts)

            # Discover all models available to this specific key
            discovered = []
            try:
                for m in client.models.list():
                    short_name = (m.name or "").replace("models/", "")
                    if "gemini" in short_name.lower():
                        discovered.append(short_name)
            except Exception as e:
                logger.info(f"Could not list models: {e}")

            if discovered:
                # Prioritize valid discovered models
                in_disc = [m for m in models_to_try if m in discovered]
                other_disc = [m for m in discovered if m not in in_disc]
                models_to_try = in_disc + other_disc + [m for m in models_to_try if m not in discovered]

            for target_model in models_to_try:
                try:
                    response = client.models.generate_content(
                        model=target_model,
                        contents='Reply in JSON: {"status": "ok"}',
                        config=types.GenerateContentConfig(response_mime_type="application/json"),
                    )
                    if response and response.text:
                        return {
                            "success": True,
                            "model": target_model,
                            "supported_models": discovered or models_to_try,
                        }
                except Exception as e:
                    last_error = str(e)
                    # If model not found (404), try next candidate model!
                    if "404" in last_error or "NOT_FOUND" in last_error or "no longer available" in last_error:
                        continue
                    # If key was blocked or leaked
                    if "ACCESS_TOKEN_TYPE_UNSUPPORTED" in last_error or "API_KEY_SERVICE_BLOCKED" in last_error:
                        return {
                            "success": False,
                            "error": "This key was disabled by Google's automated leaked-key security system (because it was visible in a screenshot). Please delete it in Google AI Studio, create a new key, and paste it directly without sharing."
                        }
                    # If key itself is invalid (400), return immediately
                    if "API_KEY_INVALID" in last_error or "400" in last_error:
                        return {
                            "success": False,
                            "error": "The Gemini API key is not valid. Please verify your key at Google AI Studio."
                        }
                    continue
        except Exception as e:
            last_error = str(e)

    # REST fallback
    for target_model in models_to_try:
        try:
            res = _call_gemini_rest('Reply in JSON: {"status": "ok"}', "", key, target_model)
            if res:
                return {"success": True, "model": target_model}
        except Exception as e:
            last_error = str(e)
            if "ACCESS_TOKEN_TYPE_UNSUPPORTED" in last_error or "API_KEY_SERVICE_BLOCKED" in last_error:
                return {
                    "success": False,
                    "error": "This key was disabled by Google's automated leaked-key security system (because it was visible in a screenshot). Please delete it in Google AI Studio, create a new key, and paste it directly without sharing."
                }

    return {"success": False, "error": last_error or "Failed to connect to Google Gemini API."}


def set_gemini_api_key(api_key: str, model: str = None) -> dict:
    """Verifies and persists a Gemini API key with automatic working model selection."""
    clean_key = (api_key or "").strip()
    if not clean_key:
        os.environ["GEMINI_API_KEY"] = ""
        setattr(settings, "GEMINI_API_KEY", "")
        _update_env_file("GEMINI_API_KEY", "")
        _AI_ASSISTANCE_CACHE.clear()
        return {
            "success": True,
            "message": "Gemini API key cleared. Reverted to OmniAI Neural Engine.",
            "status": get_gemini_status()
        }

    test_res = test_gemini_key(clean_key, model)
    if not test_res.get("success"):
        return {
            "success": False,
            "error": test_res.get("error", "Failed to validate Google Gemini API key.")
        }

    working_model = test_res.get("model", get_gemini_model(model))

    os.environ["GEMINI_API_KEY"] = clean_key
    setattr(settings, "GEMINI_API_KEY", clean_key)
    _update_env_file("GEMINI_API_KEY", clean_key)

    os.environ["GEMINI_MODEL"] = working_model
    setattr(settings, "GEMINI_MODEL", working_model)
    _update_env_file("GEMINI_MODEL", working_model)

    _AI_ASSISTANCE_CACHE.clear()
    return {
        "success": True,
        "message": f"Gemini API key verified & activated! Active model: {working_model}",
        "status": get_gemini_status()
    }


def generate_with_gemini(
    clean_title: str,
    clean_body: str,
    lang_key: str,
    config: dict,
    query: str = None,
    api_key: str = None,
    model: str = None,
) -> dict:
    """Calls Google Gemini API to produce high-fidelity news intelligence."""
    key = get_gemini_api_key(api_key)
    if not key:
        return None

    lang_name = config.get("name", "English")
    locale = config.get("locale", "en-US")
    greeting = config.get("greeting", "Hello, here is your OmniNews AI briefing.")
    headline_intro = config.get("headline_intro", "Today's top story:")
    body_intro = config.get("body_intro", "Reporting details indicate that")
    signoff = config.get("signoff", "Stay tuned with OmniNews for verified updates. Thank you.")
    is_bengali = lang_key.startswith("bn")

    chosen_model = model or get_gemini_model()
    models_to_try = [chosen_model]
    for alt in [
        "gemini-flash-lite-latest",
        "gemini-3.5-flash-lite",
        "gemini-3.1-flash-lite",
        "gemini-flash-latest",
    ]:
        if alt not in models_to_try:
            models_to_try.append(alt)

    qa_prompt = ""
    qa_schema = ""
    if query and query.strip():
        qa_prompt = (
            f'\n5. "qa_answer": Accurate and concise journalistic response answering the user\'s specific question: '
            f'"{query.strip()}" based strictly on the article content, written in {lang_name}.'
        )
        qa_schema = ',\n  "qa_answer": "string"'

    system_instruction = (
        f"You are the OmniNews AI Senior Regional Anchor and Investigative Editor. "
        f"Analyze the news article and produce a professional, authentic regional news briefing in {lang_name} ({lang_key}). "
        f"All text must be written in natural, fluent {lang_name}. "
        f"For voice_script, write a complete broadcast news anchor narration script formatted for Text-to-Speech audio reading. "
        f"If {lang_name} is Bengali (বাংলা), use natural journalistic Bengali, proper Bengali Dari (।) punctuation, "
        f"and avoid clumsy literal translations."
    )

    prompt = f"""Article Headline:
{clean_title}

Article Body:
{clean_body[:4500] if clean_body else clean_title}

Output Requirements in {lang_name}:
1. "summary": Executive news summary (2 to 3 sentences in {lang_name}).
2. "bullets": An array of 3 to 4 key takeaways in {lang_name}.
3. "eli5": Simplified overview explaining the story in plain terms ("Explain Like I'm 5" in {lang_name}).
4. "voice_script": Broadcast-ready news anchor narration script in {lang_name}. It must begin with an introduction (e.g., "{greeting} {headline_intro}"), narrate the story with clarity and context, and conclude with a sign-off ("{signoff}").{qa_prompt}

You MUST reply with ONLY a valid JSON object matching this schema:
{{
  "summary": "string",
  "bullets": ["string", "string", "string"],
  "eli5": "string",
  "voice_script": "string"{qa_schema}
}}"""

    raw_text = None
    used_model = chosen_model

    for m in models_to_try:
        try:
            if HAS_GENAI_LIB:
                http_opts = types.HttpOptions(timeout=15000) if hasattr(types, "HttpOptions") else None
                client = genai.Client(api_key=key, http_options=http_opts)
                cfg = types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    temperature=0.2,
                    response_mime_type="application/json",
                )
                response = client.models.generate_content(
                    model=m,
                    contents=prompt,
                    config=cfg,
                )
                if response and response.text:
                    raw_text = response.text
                    used_model = m
                    break
            else:
                raw_text = _call_gemini_rest(prompt, system_instruction, key, m)
                if raw_text:
                    used_model = m
                    break
        except Exception as e:
            logger.warning(f"Gemini call with model {m} failed: {e}")
            continue

    if not raw_text:
        return None

    data = None
    try:
        data = json.loads(raw_text)
    except Exception:
        match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', raw_text, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(1))
            except Exception:
                pass

    if not data or not isinstance(data, dict):
        return None

    summary = data.get("summary", "")
    bullets = data.get("bullets", [])
    if isinstance(bullets, str):
        bullets = [bullets]
    eli5 = data.get("eli5", "")
    voice_script = data.get("voice_script", "")
    qa_answer = data.get("qa_answer")

    if is_bengali and voice_script:
        voice_script = clean_bengali_text_for_speech(voice_script)
    if is_bengali and summary:
        summary = clean_bengali_text_for_speech(summary)

    return {
        "status": "success",
        "language": lang_key,
        "language_name": lang_name,
        "locale": locale,
        "title": clean_title,
        "summary": summary,
        "bullets": bullets,
        "eli5": eli5,
        "voice_script": voice_script,
        "qa_answer": qa_answer,
        "provider": f"Google Gemini ({used_model})",
        "model": used_model,
        "is_gemini": True,
        "is_bengali_enhanced": is_bengali,
    }


def generate_omni_ai_assistance(
    title: str,
    body: str,
    language: str = 'en',
    action: str = 'all',
    query: str = None,
    api_key: str = None,
    model: str = None
) -> dict:
    """
    Core AI news assistance engine:
    Uses Google Gemini API when available for advanced multi-lingual summaries,
    bullet points, broadcast narration, and interactive Q&A.
    Seamlessly falls back to OmniAI Neural Engine when offline or without key.
    """
    clean_title = clean_html(title)
    clean_body = clean_html(body)

    # Normalize language code
    lang_key = language.lower().replace('-', '_')
    if lang_key not in LANGUAGE_CONFIG:
        # Try 2-letter prefix
        lang_key = lang_key.split('_')[0]

    cache_key = (clean_title[:100], lang_key, action, query or "", api_key or "")
    if cache_key in _AI_ASSISTANCE_CACHE:
        return _AI_ASSISTANCE_CACHE[cache_key]

    config = LANGUAGE_CONFIG.get(lang_key, LANGUAGE_CONFIG['en'])

    # --- 1. Attempt Google Gemini Generation ---
    gemini_key = get_gemini_api_key(api_key)
    if gemini_key:
        try:
            gemini_res = generate_with_gemini(
                clean_title=clean_title,
                clean_body=clean_body,
                lang_key=lang_key,
                config=config,
                query=query,
                api_key=gemini_key,
                model=model,
            )
            if gemini_res and gemini_res.get("status") == "success":
                _AI_ASSISTANCE_CACHE[cache_key] = gemini_res
                return gemini_res
        except Exception as e:
            logger.warning(f"Google Gemini generation encountered error, falling back to Neural Engine: {e}")

    # --- 2. Fallback: OmniAI Regional Neural Engine ---
    lang_name = config['name']
    locale = config['locale']
    greeting = config['greeting']

    # 1. Generate English Core Extracts
    key_sentences = extract_key_sentences(clean_body or clean_title, max_sentences=4)
    if not key_sentences:
        key_sentences = [clean_title]

    # Executive Summary (2-3 sentences)
    summary_en = " ".join(key_sentences[:3])
    if len(summary_en) < 60 and clean_title not in summary_en:
        summary_en = f"{clean_title}. {summary_en}".strip()

    # Bullet Takeaways (3-4 concise points)
    bullets_en = []
    if key_sentences:
        bullets_en.append(f"Headline Overview: {clean_title}")
        for idx, s in enumerate(key_sentences[:3]):
            if s.lower() not in clean_title.lower():
                bullets_en.append(s)

    if len(bullets_en) < 2:
        bullets_en = [
            f"Key Event: {clean_title}",
            "Verified by OmniNews global dispatches.",
            "Complete coverage available in the full article."
        ]

    # Explain Like I'm 5 (ELI5)
    eli5_en = f"Here is the simple version: {clean_title}. In short, {key_sentences[0] if key_sentences else clean_title}."

    # Conversational Voice Narration Script (tailored for natural speech synthesis)
    voice_script_en = (
        f"{greeting} "
        f"Today's report: {clean_title}. "
        f"{' '.join(key_sentences[:2])} "
        f"This has been your OmniNews verified update."
    )

    # 2. Regional Translation & Voice Script Polish
    is_bengali = lang_key.startswith('bn')

    if lang_key in ('en', 'en_in'):
        summary_final = summary_en
        bullets_final = bullets_en
        eli5_final = eli5_en
        voice_script_final = voice_script_en
    elif is_bengali:
        # High-Fidelity Bengali Processing with Parallel Batch Translation
        to_translate = [clean_title, " ".join(key_sentences[:2]), summary_en, eli5_en] + list(bullets_en)
        trans_res = translate_batch(to_translate, 'bn')

        translated_title = clean_bengali_text_for_speech(trans_res[0])
        translated_body_brief = clean_bengali_text_for_speech(trans_res[1])
        summary_final = clean_bengali_text_for_speech(trans_res[2])
        eli5_raw = trans_res[3]
        eli5_final = f"সহজ ভাষায় সংক্ষেপে: {clean_bengali_text_for_speech(eli5_raw)}"
        bullets_final = [clean_bengali_text_for_speech(b) for b in trans_res[4:]]

        headline_intro = config.get('headline_intro', 'আজকের প্রধান খবর:')
        body_intro = config.get('body_intro', 'বিস্তারিত প্রতিবেদনে জানা গেছে,')
        signoff = config.get('signoff', 'খবরের নির্ভরযোগ্য ও তাৎক্ষণিক আপডেটের জন্য ওমনিনিউজের সঙ্গেই থাকুন। ধন্যবাদ।')

        # Construct broadcast narration script for Bengali Voice TTS
        voice_script_final = (
            f"{greeting} "
            f"{headline_intro} {translated_title}। "
            f"{body_intro} {translated_body_brief} "
            f"{signoff}"
        )
        voice_script_final = clean_bengali_text_for_speech(voice_script_final)
    else:
        # Other regional languages in parallel batch
        to_translate = [clean_title, " ".join(key_sentences[:2]), summary_en, eli5_en] + list(bullets_en)
        trans_res = translate_batch(to_translate, lang_key)

        translated_title = trans_res[0]
        translated_body_brief = trans_res[1]
        summary_final = trans_res[2]
        eli5_final = trans_res[3]
        bullets_final = trans_res[4:]
        voice_script_final = f"{greeting} {translated_title}। {translated_body_brief}"

    # 3. Handle Q&A if query provided
    answer_final = None
    if query and query.strip():
        answer_final = answer_question_from_context(query.strip(), clean_title, clean_body, lang_key)

    res_dict = {
        "status": "success",
        "language": lang_key,
        "language_name": lang_name,
        "locale": locale,
        "title": clean_title,
        "summary": summary_final,
        "bullets": bullets_final,
        "eli5": eli5_final,
        "voice_script": voice_script_final,
        "qa_answer": answer_final,
        "provider": "OmniAI Bengali Neural Engine" if is_bengali else "OmniAI Neural Engine",
        "is_bengali_enhanced": is_bengali,
    }
    _AI_ASSISTANCE_CACHE[cache_key] = res_dict
    if len(_AI_ASSISTANCE_CACHE) > 500:
        _AI_ASSISTANCE_CACHE.clear()
    return res_dict


# =============================================================================
# OmniAI Live Voice Assistant & Link Summarizer Services
# =============================================================================

import socket
import ipaddress
import urllib.parse
import trafilatura
import requests

def validate_safe_url(url: str) -> bool:
    """
    SSRF Protection: Validates that url is http/https and does NOT resolve to
    any loopback, private RFC-1918, link-local, multicast, or reserved IP address.
    """
    if not url or not isinstance(url, str):
        return False
    try:
        parsed = urllib.parse.urlparse(url.strip())
        if parsed.scheme not in ('http', 'https'):
            return False
        hostname = (parsed.hostname or '').lower().strip('.')
        if not hostname:
            return False

        # Resolve all IPs for the hostname and ensure none are private or restricted
        addr_info = socket.getaddrinfo(hostname, None)
        for _, _, _, _, sockaddr in addr_info:
            ip_str = sockaddr[0]
            addr = ipaddress.ip_address(ip_str)
            if (
                addr.is_private
                or addr.is_loopback
                or addr.is_link_local
                or addr.is_reserved
                or addr.is_multicast
                or addr.is_unspecified
            ):
                return False
        return True
    except Exception as e:
        logger.warning(f"SSRF validation blocked URL {url}: {e}")
        return False


def process_voice_assistant_query(
    text: str,
    user=None,
    language: str = 'en',
    article_id: int = None,
    api_key: str = None,
    model: str = None,
) -> dict:
    """
    OmniAI Voice Assistant Router & Execution Engine:
    1. Router: 'summarize today's news / my feed' -> queries user's preferred articles & summarizes.
    2. Article context: If article_id provided -> answers from specific article.
    3. Live questions (scores, weather, prices, news) -> uses google-genai with GoogleSearch tool.
    Returns: { 'speech_text': ..., 'display_text': ..., 'sources': [...] }
    """
    clean_query = (text or '').strip()
    if not clean_query:
        return {
            'speech_text': "I am listening. How can I help you today?",
            'display_text': "I'm listening! Ask me anything about today's news, live scores, weather, or financial markets.",
            'sources': [],
        }

    key = get_gemini_api_key(api_key)
    active_model = get_gemini_model(model)
    lang_code = (language or 'en').split('_')[0].split('-')[0].lower()

    # 1. Router: Detect feed / headlines summarization requests
    feed_keywords_pattern = r'\b(summarize|summary|what(\'s| is)|tell me|brief|give me|read|show).*(today(\'s)? news|my feed|headlines|top news|daily update|news today|feed)\b'
    is_feed_intent = bool(re.search(feed_keywords_pattern, clean_query, re.IGNORECASE))

    if is_feed_intent and not article_id:
        from news.models import Article
        qs = Article.objects.all()

        if user and getattr(user, 'is_authenticated', False):
            if hasattr(user, 'genres') and user.genres.exists():
                user_genre_ids = list(user.genres.values_list('id', flat=True))
                if user_genre_ids:
                    qs = qs.filter(genre_id__in=user_genre_ids)
            preferred_city = getattr(user, 'preferred_city', '')
            if preferred_city:
                qs = qs.filter(Q(region__name__icontains=preferred_city) | Q(title__icontains=preferred_city))

        articles = list(qs.order_by('-published_at', '-id')[:8])
        if not articles:
            articles = list(Article.objects.all().order_by('-published_at', '-id')[:8])

        sources = [{'title': a.title, 'url': a.url} for a in articles[:6]]

        articles_context = "\n\n".join([
            f"Headline {i+1}: {a.title}\nSource: {a.source.name if a.source else 'Global Wire'}\nSnippet: {a.body[:250]}"
            for i, a in enumerate(articles)
        ])

        if HAS_GENAI_LIB and key:
            try:
                client = genai.Client(api_key=key)
                prompt = f"""You are OmniAI, a world-class broadcast news anchor.
The user asked: "{clean_query}"
Target language: {language}

Below are the latest verified headlines from the user's news feed:
{articles_context}

Please generate:
1. speech_text: A natural, spoken news briefing (around 3-4 sentences, conversational, warm, no asterisks, no raw URLs, designed to be read aloud via voice assistant).
2. display_text: An organized markdown summary for the screen featuring key headlines and bullet takeaways.

Return the result as a strict JSON object with keys "speech_text" and "display_text".
"""
                resp = client.models.generate_content(
                    model=active_model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        temperature=0.3,
                        response_mime_type="application/json",
                    ),
                )
                parsed = json.loads(resp.text)
                return {
                    'speech_text': parsed.get('speech_text', '').strip(),
                    'display_text': parsed.get('display_text', '').strip(),
                    'sources': sources,
                }
            except Exception as e:
                logger.warning(f"Gemini feed summarization fallback: {e}")

        # Non-AI Fallback for Feed Summarization
        headlines = [a.title for a in articles[:4]]
        speech = f"Here is your top news briefing: {'. '.join(headlines)}."
        display = "### Today's Top News Briefing\n\n" + "\n".join([f"- **{a.title}** ({a.source.name if a.source else 'Wire'})" for a in articles[:5]])
        return {
            'speech_text': speech,
            'display_text': display,
            'sources': sources,
        }

    # 2. Article-specific Q&A or summarization
    if article_id:
        from news.models import Article
        article = Article.objects.filter(id=article_id).first()
        if article:
            sources = [{'title': article.title, 'url': article.url}]
            if HAS_GENAI_LIB and key:
                try:
                    client = genai.Client(api_key=key)
                    prompt = f"""You are OmniAI, an intelligent news assistant.
The user is asking: "{clean_query}"
Article Title: {article.title}
Article Body: {article.body}
Target language: {language}

Provide:
1. speech_text: A clear, conversational spoken answer (no markdown, no asterisks, natural for TTS).
2. display_text: A well-structured markdown answer for display.

Return as a JSON object with keys "speech_text" and "display_text".
"""
                    resp = client.models.generate_content(
                        model=active_model,
                        contents=prompt,
                        config=types.GenerateContentConfig(
                            temperature=0.2,
                            response_mime_type="application/json",
                        ),
                    )
                    parsed = json.loads(resp.text)
                    return {
                        'speech_text': parsed.get('speech_text', '').strip(),
                        'display_text': parsed.get('display_text', '').strip(),
                        'sources': sources,
                    }
                except Exception as e:
                    logger.warning(f"Article Q&A Gemini fallback: {e}")

            return {
                'speech_text': f"Regarding {article.title}: {article.body[:250]}.",
                'display_text': f"**{article.title}**\n\n{article.body[:400]}...",
                'sources': sources,
            }

    # 3. Live Questions with Google Search Grounding (Live Scores, Weather, Financial Prices, Current Events)
    if HAS_GENAI_LIB and key:
        try:
            client = genai.Client(api_key=key)
            prompt = f"""You are OmniAI Voice Assistant, an intelligent news anchor and factual assistant.
User query: "{clean_query}"
Language: {language}

Instructions:
1. Answer accurately using Google Search grounding for real-time live facts (cricket/sports scores, weather, stock prices, breaking events).
2. Output a natural spoken briefing ('speech_text') that sounds conversational and human when spoken aloud (no asterisks, no raw markdown, clean pauses).
3. Output a readable, organized display answer ('display_text') with key highlights.

Format your response as a valid JSON object with keys:
"speech_text": "...",
"display_text": "..."
"""
            resp = client.models.generate_content(
                model=active_model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    tools=[types.Tool(google_search=types.GoogleSearch())],
                    temperature=0.3,
                ),
            )

            response_raw = resp.text or ""
            # Extract grounded sources
            sources = []
            seen_urls = set()
            candidates = getattr(resp, 'candidates', None)
            if candidates and len(candidates) > 0:
                gm = getattr(candidates[0], 'grounding_metadata', None)
                if gm and hasattr(gm, 'grounding_chunks') and gm.grounding_chunks:
                    for chunk in gm.grounding_chunks:
                        web = getattr(chunk, 'web', None)
                        if web and getattr(web, 'uri', None):
                            uri = web.uri
                            title = getattr(web, 'title', None) or uri
                            if uri not in seen_urls:
                                seen_urls.add(uri)
                                sources.append({'title': title, 'url': uri})

            # Parse JSON if model returned JSON, or parse text
            speech_text = ""
            display_text = ""
            try:
                # Find JSON block if wrapped in markdown
                json_str = response_raw.strip()
                if "```json" in json_str:
                    json_str = json_str.split("```json")[1].split("```")[0].strip()
                elif "```" in json_str:
                    json_str = json_str.split("```")[1].split("```")[0].strip()
                parsed = json.loads(json_str)
                speech_text = parsed.get("speech_text", "")
                display_text = parsed.get("display_text", "")
            except Exception:
                display_text = response_raw
                # Clean speech_text from display text
                clean_speech = re.sub(r'[\*\_#~`\^\|\\]', '', response_raw)
                clean_speech = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', clean_speech)
                speech_text = clean_speech[:400].strip()

            if not speech_text:
                speech_text = re.sub(r'[\*\_#~`\^\|\\]', '', display_text)[:350].strip()

            return {
                'speech_text': speech_text,
                'display_text': display_text,
                'sources': sources,
            }
        except Exception as e:
            logger.warning(f"Google Search grounded voice assistant fallback: {e}")
            try:
                # Direct generation without Google Search grounding tool (avoids 429 quota exhaustion)
                simple_prompt = f"""You are OmniAI Voice Assistant, an intelligent news anchor and factual assistant.
User query: "{clean_query}"
Language: {language}

Instructions:
1. Answer accurately and directly in the requested language ({language}).
2. Output a concise spoken response (1-2 sentences, suitable for speech synthesis).
3. Do not include markdown asterisks, raw URLs, or formatting artifacts.
"""
                resp = client.models.generate_content(
                    model=active_model,
                    contents=simple_prompt,
                )
                raw_text = (resp.text or "").strip()
                if raw_text:
                    clean_speech = re.sub(r'[\*\_#~`\^\|\\]', '', raw_text).strip()
                    return {
                        'speech_text': clean_speech,
                        'display_text': raw_text,
                        'sources': [],
                    }
            except Exception as e2:
                logger.warning(f"Direct Gemini voice assistant fallback failed: {e2}")

    # Fallback if no Gemini key or network failure
    # Detect language for localized fallback message
    is_bn = any('\u0980' <= c <= '\u09ff' for c in clean_query) or language.startswith('bn')
    is_hi = any('\u0900' <= c <= '\u097f' for c in clean_query) or language.startswith('hi')
    is_es = language.startswith('es')

    if is_bn:
        speech = f"আমি আপনার প্রশ্ন '{clean_query}' বুঝতে পেরেছি। লাইভ সংযোগ স্থাপন করা হচ্ছে।"
        disp = f"### OmniAI প্রতিক্রিয়া\n\nআপনার প্রশ্ন: **{clean_query}**\n\nস্মার্ট সহকারী লাইভ আপডেট হচ্ছে।"
    elif is_hi:
        speech = f"मैंने आपका प्रश्न '{clean_query}' समझ लिया है। लाइव जानकारी अपडेट की जा रही है।"
        disp = f"### OmniAI उत्तर\n\nआपका सवाल: **{clean_query}**\n\nस्मार्ट सहायक लाइव अपडेट हो रहा है।"
    elif is_es:
        speech = f"He recibido su consulta sobre '{clean_query}'. El asistente está procesando su respuesta."
        disp = f"### OmniAI Respuesta\n\nSu consulta: **{clean_query}**\n\nEl asistente inteligente se está actualizando."
    else:
        speech = f"I received your request about {clean_query}. OmniAI is ready to assist you."
        disp = f"### OmniAI Response\n\nI received your query: **{clean_query}**.\n\nPlease ensure your connection is active."

    return {
        'speech_text': speech,
        'display_text': disp,
        'sources': [],
    }


def summarize_web_link(
    url: str,
    language: str = 'en',
    length: str = 'medium',
    api_key: str = None,
    model: str = None,
) -> dict:
    """
    Summarizes any web link with strict SSRF defense.
    1. Validates URL (http/https only, blocks private and loopback IPs).
    2. Tries Gemini url_context tool, falls back to requests + trafilatura.
    3. Summarizes extracted content into executive summary, bullets, and speech script.
    """
    url_clean = (url or '').strip()
    if not validate_safe_url(url_clean):
        raise ValueError("Invalid URL or address is prohibited (private/internal networks are blocked).")

    key = get_gemini_api_key(api_key)
    active_model = get_gemini_model(model)

    extracted_title = ""
    extracted_text = ""

    # Strategy 1: Try Gemini with url_context tool if supported
    if HAS_GENAI_LIB and key and hasattr(types, 'UrlContext'):
        try:
            client = genai.Client(api_key=key)
            prompt = f"Please summarize the article at this link: {url_clean}"
            resp = client.models.generate_content(
                model=active_model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    tools=[types.Tool(url_context=types.UrlContext())],
                    temperature=0.2,
                ),
            )
            if resp.text and len(resp.text.strip()) > 80:
                extracted_text = resp.text.strip()
        except Exception as e:
            logger.debug(f"url_context tool failed or unsupported, using trafilatura fallback: {e}")

    # Strategy 2: Fallback to requests + trafilatura
    if not extracted_text:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        resp = requests.get(url_clean, headers=headers, timeout=9, stream=True)
        resp.raise_for_status()

        # Read up to 5 MB cap
        chunks = []
        total_bytes = 0
        for chunk in resp.iter_content(chunk_size=32768):
            chunks.append(chunk)
            total_bytes += len(chunk)
            if total_bytes > 5 * 1024 * 1024:
                break
        html_bytes = b"".join(chunks)
        html_str = html_bytes.decode('utf-8', errors='ignore')

        extracted_text = trafilatura.extract(html_str, include_comments=False, include_tables=False) or ""
        metadata = trafilatura.extract_metadata(html_str)
        if metadata and metadata.title:
            extracted_title = metadata.title

    if not extracted_title:
        parsed_p = urllib.parse.urlparse(url_clean)
        extracted_title = parsed_p.path.split('/')[-1].replace('-', ' ').replace('_', ' ').title() or parsed_p.netloc

    if not extracted_text or len(extracted_text.strip()) < 40:
        extracted_text = f"Content from {url_clean} - {extracted_title}"

    # Target length guide
    length_lower = (length or 'medium').lower()
    summary_instructions = {
        'short': "Provide a brief 1-2 paragraph executive summary and 3 punchy takeaways.",
        'medium': "Provide a comprehensive 3-paragraph summary and 4 key bullet takeaways.",
        'detailed': "Provide an in-depth 4-5 paragraph detailed analysis with 5 exhaustive takeaways and implications.",
    }.get(length_lower, "Provide a comprehensive summary and 4 bullet takeaways.")

    # Summarize with Gemini
    if HAS_GENAI_LIB and key:
        try:
            client = genai.Client(api_key=key)
            prompt = f"""You are OmniAI Link Intelligence Engine.
Summarize the following web content accurately.
Target language: {language}
Length requirement: {summary_instructions}

Article Title: {extracted_title}
URL: {url_clean}
Content:
{extracted_text[:12000]}

Produce a strict JSON response with these keys:
"title": "{extracted_title}",
"summary": "...",
"bullets": ["...", "...", "..."],
"speech_text": "A natural 3-sentence broadcast briefing suitable for voice readout (no asterisks, no raw URLs).",
"estimated_read_time": "e.g. 3 min read"
"""
            resp = client.models.generate_content(
                model=active_model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.2,
                    response_mime_type="application/json",
                ),
            )
            parsed = json.loads(resp.text)
            return {
                "status": "success",
                "url": url_clean,
                "title": parsed.get("title") or extracted_title,
                "summary": parsed.get("summary") or extracted_text[:400],
                "bullets": parsed.get("bullets") or [extracted_title],
                "speech_text": parsed.get("speech_text") or f"Here is a summary of {extracted_title}.",
                "estimated_read_time": parsed.get("estimated_read_time") or "2 min read",
                "sources": [{"title": extracted_title, "url": url_clean}],
                "language": language,
            }
        except Exception as e:
            logger.warning(f"Gemini link summarizer fallback: {e}")

    # Fallback summary
    paragraphs = [p.strip() for p in extracted_text.split('\n') if len(p.strip()) > 30]
    fallback_summary = " ".join(paragraphs[:3]) if paragraphs else extracted_text[:400]
    fallback_bullets = [p[:100] for p in paragraphs[3:7]] if len(paragraphs) > 3 else [extracted_title]

    return {
        "status": "success",
        "url": url_clean,
        "title": extracted_title,
        "summary": fallback_summary,
        "bullets": fallback_bullets,
        "speech_text": f"Summary of {extracted_title}: {fallback_summary[:250]}.",
        "estimated_read_time": "2 min read",
        "sources": [{"title": extracted_title, "url": url_clean}],
        "language": language,
    }
