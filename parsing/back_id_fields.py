"""Turn Document Intelligence lines from an Egyptian national ID back into fields.

The read model returns lines and boxes. This module places those lines.
Nothing is inferred from a neighbouring row.

On this card the national ID and the issuing date share the top row.
The profession and the workplace are the lines under that, and both go
in profession_workplace. One line or two, it is the same field. Gender,
religion, and marital status share the next row, so all three are read
from that row. The expiry line is the one that says سارية حتى. The
national ID is a 14-digit number, including one read backwards.

The husband's name is the line under أنثى, مسلمة, and متزوجة. It is
filled only when that line was read.
"""

import math
import re
import statistics

ARABIC_TO_ENGLISH_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
_EASTERN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")
_DIACRITICS = re.compile(r"[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED\u0640]")
_ARABIC_CHAR = r"[\u0600-\u06FF]"
_DATE_YMD = re.compile(
    r"(?<!\d)(\d{4})\s*[\/\-.]\s*(\d{1,2})\s*[\/\-.]\s*(\d{1,2})(?!\d)"
)
_DATE_DMY = re.compile(
    r"(?<!\d)(\d{1,2})\s*[\/\-.]\s*(\d{1,2})\s*[\/\-.]\s*(\d{4})(?!\d)"
)
_DATE_YM = re.compile(
    r"(?<!\d)(\d{4})\s*[\/\-.]\s*(\d{1,2})(?!\s*[\/\-.]\s*\d)(?!\d)"
)
_CARD_SERIAL = re.compile(r"^[a-z]{1,4}\d{5,12}$")

_HEADER_WORD_SOURCES = (
    "جمهورية", "مصر", "العربية", "وزارة", "الداخلية",
    "بطاقة", "تحقيق", "شخصية", "الرقم", "القومي", "القومى",
    "قطاع", "الأحوال", "المدنية",
    "arab", "republic", "of", "egypt", "ministry", "interior", "card",
)
_HEADER_PHRASES = (
    "بطاقه تحقيق",
    "تحقيق الشخصيه",
    "جمهوريه مصر",
    "مصر العربيه",
    "وزاره الداخليه",
    "قطاع الاحوال",
)
_LABEL_SOURCES = (
    "الحالة الاجتماعية",
    "تاريخ الإصدار",
    "تاريخ الاصدار",
    "الرقم القومي",
    "الرقم القومى",
    "جهة العمل",
    "الديانة",
    "المهنة",
    "النوع",
    "الحالة",
)
_GENDER_SOURCES = ("ذكر", "أنثى", "انثى")
_RELIGION_SOURCES = ("مسلم", "مسلمة", "مسيحي", "مسيحية", "يهودي", "يهودية")
_MARITAL_SOURCES = (
    "متزوجة", "متزوج", "عزباء", "أعزب", "مطلقة", "مطلق", "أرملة", "أرمل",
)
OUTPUT_FIELDS = (
    "national_id",
    "issuing_date",
    "profession_workplace",
    "gender",
    "religion",
    "marital_status",
    "husband_name",
    "valid_until",
)
# Printed on every card. Husband is required only when the card says أنثى and متزوجة.
REQUIRED_FIELDS = (
    "national_id",
    "issuing_date",
    "profession_workplace",
    "gender",
    "religion",
    "marital_status",
    "valid_until",
)

UNREADABLE = "can't be read. Please upload a better quality image or a clearer image."


def _folded_phrases(sources: tuple[str, ...]) -> tuple[str, ...]:
    phrases = {fold_arabic(source) for source in sources}
    phrases.discard("")
    return tuple(sorted(phrases, key=len, reverse=True))


def _to_english_digits(text: str) -> str:
    return (text or "").translate(ARABIC_TO_ENGLISH_DIGITS).translate(_EASTERN_DIGITS)


def fold_arabic(text: str) -> str:
    """Fold hamza, alef maqsura, and ta marbuta, and use English digits."""
    folded = _to_english_digits(text).lower()
    for src, dst in (
        ("أ", "ا"), ("إ", "ا"), ("آ", "ا"), ("ى", "ي"), ("ة", "ه"),
        ("ؤ", "و"), ("ئ", "ي"),
    ):
        folded = folded.replace(src, dst)
    folded = _DIACRITICS.sub("", folded)
    folded = re.sub(r"[^\w\s]", " ", folded, flags=re.UNICODE)
    return re.sub(r"\s+", " ", folded).strip()


def contains_phrase(folded_line: str, phrase: str) -> bool:
    """Match a whole word. المنيا must not match inside المنياوي."""
    if not phrase:
        return False
    pattern = rf"(?<![\u0600-\u06FF\d]){re.escape(phrase)}(?![\u0600-\u06FF])"
    return re.search(pattern, folded_line or "") is not None


HEADER_WORDS = {fold_arabic(word) for word in _HEADER_WORD_SOURCES}
LABEL_PHRASES = _folded_phrases(_LABEL_SOURCES)
GENDER_PHRASES = _folded_phrases(_GENDER_SOURCES)
RELIGION_PHRASES = _folded_phrases(_RELIGION_SOURCES)
MARITAL_PHRASES = _folded_phrases(_MARITAL_SOURCES)
FEMALE = fold_arabic("أنثى")
MARRIED_WOMAN = fold_arabic("متزوجة")


def _word_pairs(text: str) -> list[tuple[str, str]]:
    pairs = []
    for word in (text or "").split():
        folded = fold_arabic(word)
        if folded:
            pairs.append((word, folded))
    return pairs


def strip_label(text: str) -> str:
    pairs = _word_pairs(text)
    folded_words = [folded for _, folded in pairs]
    for label in LABEL_PHRASES:
        label_words = label.split()
        if folded_words[:len(label_words)] == label_words:
            return " ".join(word for word, _ in pairs[len(label_words):]).strip()
    return " ".join(word for word, _ in pairs).strip()


def _exact_phrase(text: str, phrases: tuple[str, ...]) -> str | None:
    pairs = _word_pairs(text)
    folded = " ".join(folded for _, folded in pairs)
    for phrase in phrases:
        if folded == phrase:
            return " ".join(word for word, _ in pairs)
    return None


def _leading_phrase(text: str, phrases: tuple[str, ...]) -> tuple[str | None, str | None]:
    pairs = _word_pairs(text)
    folded_words = [folded for _, folded in pairs]
    for phrase in phrases:
        phrase_words = phrase.split()
        if folded_words[:len(phrase_words)] != phrase_words:
            continue
        status = " ".join(word for word, _ in pairs[:len(phrase_words)])
        rest = " ".join(word for word, _ in pairs[len(phrase_words):]).strip()
        return status, rest or None
    return None, None


def _match_gender(text: str) -> str | None:
    return _exact_phrase(strip_label(text), GENDER_PHRASES)


def _match_religion(text: str) -> str | None:
    return _exact_phrase(strip_label(text), RELIGION_PHRASES)


def _match_marital(text: str) -> tuple[str | None, str | None]:
    return _leading_phrase(strip_label(text), MARITAL_PHRASES)


def _is_header_word(word: str) -> bool:
    if word in HEADER_WORDS:
        return True
    return word.startswith("ال") and word[2:] in HEADER_WORDS


def _is_header_line(folded_line: str) -> bool:
    words = folded_line.split()
    if not words:
        return True
    if all(_is_header_word(word) for word in words):
        return True
    if any(phrase in folded_line for phrase in _HEADER_PHRASES):
        return True
    if "العربيه" in words and ("قصر" in words or "مصر" in words or "جمهوريه" in words):
        return True
    return False


def _digits(text: str) -> str:
    return re.sub(r"\D", "", _to_english_digits(text))


def _arabic_letters(text: str) -> list[str]:
    """Letters only. Arabic-Indic digits are converted before this count."""
    return re.findall(_ARABIC_CHAR, fold_arabic(text))


def _plausible_national_id(value: str) -> bool:
    if len(value) != 14 or not value.isdigit() or value[0] not in "23":
        return False
    month, day = int(value[3:5]), int(value[5:7])
    return 1 <= month <= 12 and 1 <= day <= 31


def _parse_full_date(text: str) -> str | None:
    digits = _to_english_digits(text)
    match = _DATE_YMD.search(digits)
    if match:
        year, month, day = (int(match.group(1)), int(match.group(2)), int(match.group(3)))
    else:
        match = _DATE_DMY.search(digits)
        if not match:
            return None
        day, month, year = (int(match.group(1)), int(match.group(2)), int(match.group(3)))
    if not (1950 <= year <= 2100 and 1 <= month <= 12 and 1 <= day <= 31):
        return None
    return f"{year:04d}/{month:02d}/{day:02d}"


def _parse_issuing_date(text: str) -> str | None:
    """Year and month only. A full date is the expiry or the photo date."""
    digits = _to_english_digits(text)
    match = _DATE_YM.search(digits)
    if not match:
        return None
    year, month = int(match.group(1)), int(match.group(2))
    if not (1950 <= year <= 2100 and 1 <= month <= 12):
        return None
    remainder = _DATE_YM.sub(" ", digits)
    if re.search(_ARABIC_CHAR, remainder):
        return None
    return f"{year:04d}/{month:02d}"


def _is_valid_until_line(text: str) -> bool:
    folded = fold_arabic(text)
    return contains_phrase(folded, "ساريه") or contains_phrase(folded, "ساري")


def _is_serial(text: str) -> bool:
    compact = fold_arabic(text).replace(" ", "")
    return _CARD_SERIAL.fullmatch(compact) is not None


def _is_barcode(text: str) -> bool:
    if _parse_issuing_date(text) or _parse_full_date(text):
        return False
    return len(_digits(text)) >= 12 and len(_arabic_letters(text)) < 3


def _is_short_number(text: str) -> bool:
    """The small '14' by the eagle is not a field. A date is not this."""
    if _parse_issuing_date(text) or _parse_full_date(text):
        return False
    compact = fold_arabic(text).replace(" ", "")
    return compact.isdigit() and 1 <= len(compact) <= 6


def _read_status(text: str) -> dict | None:
    """Gender, religion, and marital status.

    On this card the three words share one row, so a line may hold one word
    or all three. A husband's name can follow متزوجة on that same line.
    """
    pairs = _word_pairs(strip_label(text))
    if not pairs:
        return None
    gender = religion = marital = None
    other = []
    gender_words = set(GENDER_PHRASES)
    religion_words = set(RELIGION_PHRASES)
    marital_words = set(MARITAL_PHRASES)
    for word, folded in pairs:
        if gender is None and folded in gender_words:
            gender = word
        elif religion is None and folded in religion_words:
            religion = word
        elif marital is None and folded in marital_words:
            marital = word
        else:
            other.append(word)
    if gender is None and religion is None and marital is None:
        return None
    # Other words are the husband's name only when متزوجة is on this line.
    # A gender or religion word with extra text is not the status row.
    husband = " ".join(other).strip() or None
    if husband and marital is None:
        return None
    return {
        "gender": gender,
        "religion": religion,
        "marital": marital,
        "husband": husband,
    }


def _is_female(gender: str | None) -> bool:
    return fold_arabic(gender or "") == FEMALE


def _is_married_woman(status: str | None) -> bool:
    return fold_arabic(status or "") == MARRIED_WOMAN


def _line_box(polygon) -> dict | None:
    if not polygon:
        return None
    if isinstance(polygon[0], (int, float)):
        if len(polygon) < 8:
            return None
        xs, ys = polygon[0::2], polygon[1::2]
    elif isinstance(polygon[0], dict):
        xs = [float(point.get("x", 0)) for point in polygon]
        ys = [float(point.get("y", 0)) for point in polygon]
    else:
        return None
    if not xs or not ys:
        return None
    top, bottom = min(ys), max(ys)
    left, right = min(xs), max(xs)
    return {
        "left": left,
        "right": right,
        "top": top,
        "bottom": bottom,
        "y": (top + bottom) / 2,
        "height": max(bottom - top, 0.0),
    }


def _polygon_points(polygon) -> list[tuple[float, float]]:
    if not polygon:
        return []
    if isinstance(polygon[0], (int, float)):
        return [(float(x), float(y)) for x, y in zip(polygon[0::2], polygon[1::2])]
    if isinstance(polygon[0], dict):
        return [(float(point.get("x", 0)), float(point.get("y", 0))) for point in polygon]
    return []


def lines_from_analyze_result(payload: dict) -> list[dict]:
    """Accept either the poll body or the analyzeResult object."""
    result = payload.get("analyzeResult", payload) if isinstance(payload, dict) else {}
    lines = []
    for page in result.get("pages") or []:
        page_width = float(page.get("width") or 0)
        page_height = float(page.get("height") or 0)
        for line in page.get("lines") or []:
            content = re.sub(r"\s+", " ", (line.get("content") or "").strip())
            polygon = line.get("polygon") or line.get("boundingPolygon")
            points = _polygon_points(polygon)
            box = _line_box(polygon)
            lines.append({
                "content": content,
                "page_width": page_width,
                "page_height": page_height,
                "points": points,
                **(box or {
                    "left": None, "right": None, "top": None,
                    "bottom": None, "y": None, "height": None,
                }),
            })
    return lines


def _cluster_rows(lines: list[dict]) -> list[list[dict]]:
    """Group lines whose vertical centers sit on one printed row."""
    ordered = sorted(
        (line for line in lines if line.get("y") is not None),
        key=lambda line: line["y"],
    )
    if not ordered:
        return []
    heights = [line["height"] for line in ordered if line.get("height")]
    if heights:
        tolerance = statistics.median(heights) * 0.55
    else:
        span = ordered[-1]["y"] - ordered[0]["y"]
        tolerance = max(span * 0.04, 0.01)
    rows: list[list[dict]] = []
    for line in ordered:
        if rows and line["y"] - rows[-1][-1]["y"] <= tolerance:
            rows[-1].append(line)
        else:
            rows.append([line])
    return rows


def _row_digit_pieces(row: list[dict]) -> list[str]:
    """Digit groups on one row, left to right, with the printed dates removed."""
    ordered = sorted(row, key=lambda line: (line.get("left") is None, line.get("left") or 0))
    pieces = []
    for line in ordered:
        text = _to_english_digits(line.get("content") or "")
        text = _DATE_YMD.sub(" ", text)
        text = _DATE_DMY.sub(" ", text)
        text = _DATE_YM.sub(" ", text)
        pieces.extend(re.findall(r"\d+", text))
    return pieces


def _consider_id(ranked: list, digits: str, y: float, on_date_row: bool) -> None:
    forward = _plausible_national_id(digits)
    reverse = digits[::-1]
    backward = reverse != digits and _plausible_national_id(reverse)
    if forward:
        ranked.append((0 if on_date_row else 1, 0, y, digits))
    if backward:
        ranked.append((0 if on_date_row else 1, 1, y, reverse))


def extract_national_id(lines: list[dict]) -> str:
    """Join digit fragments on the issuing-date row. Accept a reversed read.

    The watermark often splits the 14 digits into two OCR lines. Each piece
    is too short on its own. The pieces sit on the same row as ٢٠٢٣/١١.
    """
    ranked = []
    rows = _cluster_rows(lines) or [[line] for line in lines]
    for row in rows:
        pieces = _row_digit_pieces(row)
        if not pieces:
            continue
        y = min((line["y"] for line in row if line.get("y") is not None), default=1e9)
        on_date_row = any(_parse_issuing_date(line.get("content") or "") for line in row)
        _consider_id(ranked, "".join(pieces), y, on_date_row)
        substantial = [piece for piece in pieces if len(piece) >= 3]
        if substantial and substantial != pieces:
            _consider_id(ranked, "".join(substantial), y, on_date_row)
        for piece in pieces:
            _consider_id(ranked, piece, y, on_date_row)
        if len(pieces) >= 2:
            joined = "".join(piece[::-1] for piece in pieces)
            _consider_id(ranked, joined[::-1], y, on_date_row)
    if not ranked:
        return ""
    ranked.sort(key=lambda item: (item[0], item[1], item[2]))
    return ranked[0][3]


def _is_national_id_line(text: str, national_id: str) -> bool:
    if not national_id:
        return False
    digits = _digits(text)
    if national_id not in digits and national_id not in digits[::-1]:
        return False
    words = [word for word in fold_arabic(text).split() if not word.isdigit()]
    if words and not all(_is_header_word(word) or word in LABEL_PHRASES for word in words):
        if len(_arabic_letters(text)) >= 3:
            return False
    return True


def _estimate_pitch(lines: list[dict]) -> float | None:
    """Normal gap between rows. A gap about twice that size is a missing row.

    Words on the same row are a few pixels apart and are ignored. A wrapped
    line is about one line-height, so it does not become the row pitch.
    """
    ordered = sorted(
        (line for line in lines if line.get("y") is not None),
        key=lambda line: line["y"],
    )
    gaps = [
        below["y"] - above["y"]
        for above, below in zip(ordered, ordered[1:])
        if below["y"] > above["y"]
    ]
    heights = [line["height"] for line in ordered if line.get("height")]
    median_height = statistics.median(heights) if heights else None
    height_pitch = median_height * 1.55 if median_height else None
    if median_height:
        gaps = [gap for gap in gaps if gap >= median_height * 0.45]
    if not gaps:
        return height_pitch
    row_gaps = [gap for gap in gaps if gap > median_height * 1.35] if median_height else gaps
    chosen = row_gaps or gaps
    smallest = min(chosen)
    normal = [gap for gap in chosen if gap <= smallest * 1.35]
    pitch = statistics.median(normal)
    if height_pitch and pitch > height_pitch * 1.65:
        return height_pitch
    return pitch


def _right_aligned(lines: list[dict]) -> list[dict]:
    """Keep the profession stack, which shares the right edge."""
    usable = [
        line for line in lines
        if line.get("right") is not None and line.get("page_width")
    ]
    if len(usable) < 2:
        return list(lines)
    max_right = max(line["right"] for line in usable)
    width = statistics.median(line["page_width"] for line in usable) or 1
    limit = width * 0.18
    kept = [line for line in usable if max_right - line["right"] <= limit]
    unboxed = [
        line for line in lines
        if line.get("right") is None or not line.get("page_width")
    ]
    return kept + unboxed


def _join(cluster: list[dict]) -> str:
    ordered = sorted(cluster, key=lambda item: (item.get("y") or 0, -(item.get("right") or 0)))
    return " ".join(strip_label(line["content"]) for line in ordered).strip()


def _clean_text_field(text: str | None) -> str | None:
    if not text:
        return None
    cleaned = strip_label(text)
    folded = fold_arabic(cleaned)
    if not folded or _is_header_line(folded) or _is_serial(cleaned) or _is_barcode(cleaned):
        return None
    if _match_gender(cleaned) or _match_religion(cleaned):
        return None
    status, _rest = _match_marital(cleaned)
    if status and fold_arabic(cleaned) == fold_arabic(status):
        return None
    if _parse_full_date(cleaned) or _parse_issuing_date(cleaned):
        return None
    if len(_arabic_letters(cleaned)) < 2:
        return None
    return cleaned


def _place_profession_workplace(
    unlabeled: list[dict],
    floor_y: float | None,
    top_y: float | None,
    pitch: float | None,
) -> str | None:
    """The job and the workplace, one field.

    Two printed lines are joined. A card with only one of those lines
    still fills the same field.
    """
    if floor_y is None or not pitch:
        return None
    band = []
    for line in unlabeled:
        if line.get("y") is None:
            continue
        y = line["y"]
        if y >= floor_y - pitch * 0.45:
            continue
        if top_y is not None and y <= top_y + pitch * 0.35:
            continue
        band.append(line)
    band = _right_aligned(band)
    if not band:
        return None
    return _clean_text_field(_join(band))


def _place_husband(
    unlabeled: list[dict],
    status_lines: list[dict | None],
    valid_line: dict | None,
    pitch: float | None,
) -> str | None:
    """The husband's name is the text under the gender, religion, and marital row.

    On a married woman's card that line sits directly under أنثى / مسلمة / متزوجة
    and above البطاقة سارية حتى. The gap is often shorter than the gap between
    the other rows, so it is not required to be one pitch below متزوجة.
    """
    anchors = [line for line in status_lines if line and line.get("y") is not None]
    if not anchors:
        return None
    heights = [line["height"] for line in anchors if line.get("height")]
    median_height = statistics.median(heights) if heights else 0.0
    separation = median_height * 0.4 if median_height else (pitch or 0) * 0.25
    if not separation:
        return None
    row_y = statistics.median(line["y"] for line in anchors)
    lower = row_y + separation
    if valid_line and valid_line.get("y") is not None:
        upper = valid_line["top"] if valid_line.get("top") is not None else valid_line["y"] - separation
    elif pitch:
        upper = row_y + pitch * 1.9
    else:
        upper = row_y + separation * 6
    chosen = [
        line for line in unlabeled
        if line.get("y") is not None and lower < line["y"] < upper
    ]
    if not chosen:
        return None
    chosen.sort(key=lambda line: (line["y"], -(line.get("right") or 0)))
    return _clean_text_field(_join(chosen))


def _empty_back(national_id: str = "") -> dict:
    data = {field: None for field in OUTPUT_FIELDS}
    data["national_id"] = national_id or None
    return data


def _points_of(line: dict) -> list[tuple[float, float]]:
    points = line.get("points")
    if points:
        return [(float(x), float(y)) for x, y in points]
    if line.get("left") is not None and line.get("top") is not None and line.get("right") is not None:
        left, right = float(line["left"]), float(line["right"])
        top, bottom = float(line["top"]), float(line.get("bottom") if line.get("bottom") is not None else line["top"])
        return [(left, top), (right, top), (right, bottom), (left, bottom)]
    return []


def _axis_angle(theta: float) -> float:
    """Collapse a line direction to the range [-90, 90) degrees, in radians."""
    return (theta + math.pi / 2) % math.pi - math.pi / 2


def _median_axis_angle(lines: list[dict]) -> float:
    angles = []
    for line in lines:
        points = _points_of(line)
        if len(points) < 2:
            continue
        best_len = -1.0
        best = None
        for start, end in zip(points, points[1:] + points[:1]):
            dx, dy = end[0] - start[0], end[1] - start[1]
            length = dx * dx + dy * dy
            if length > best_len:
                best_len = length
                best = (dx, dy)
        if not best or best_len <= 0:
            continue
        angles.append(_axis_angle(math.atan2(best[1], best[0])))
    if not angles:
        return 0.0
    angles.sort()
    return angles[len(angles) // 2]


def _rotate_lines(lines: list[dict], theta: float) -> list[dict]:
    """Rotate every line box by theta radians. Text stays attached to its box."""
    if abs(theta) < 0.02 or not lines:
        return lines
    cosine, sine = math.cos(theta), math.sin(theta)

    def spin(x: float, y: float) -> tuple[float, float]:
        return (x * cosine - y * sine, x * sine + y * cosine)

    spun = []
    all_points = []
    for line in lines:
        points = [spin(x, y) for x, y in _points_of(line)]
        spun.append(points)
        all_points.extend(points)
    if not all_points:
        return lines
    min_x = min(point[0] for point in all_points)
    min_y = min(point[1] for point in all_points)
    max_x = max(point[0] for point in all_points)
    max_y = max(point[1] for point in all_points)
    rotated = []
    for line, points in zip(lines, spun):
        points = [(x - min_x, y - min_y) for x, y in points]
        xs = [point[0] for point in points]
        ys = [point[1] for point in points]
        left, right = min(xs), max(xs)
        top, bottom = min(ys), max(ys)
        rotated.append({
            **line,
            "points": points,
            "left": left,
            "right": right,
            "top": top,
            "bottom": bottom,
            "y": (top + bottom) / 2,
            "height": max(bottom - top, 0.0),
            "page_width": max_x - min_x,
            "page_height": max_y - min_y,
        })
    return rotated


def _orientation_variants(lines: list[dict]) -> list[list[dict]]:
    """Upright text, then the same card turned 180 degrees.

    A sideways photo is rotated until the lines are horizontal. Both
    vertical directions are kept, and the caller keeps the one that
    fills more fields.
    """
    if not any(line.get("y") is not None for line in lines):
        return [lines]
    angle = _median_axis_angle(lines)
    normalized = _rotate_lines(lines, -angle) if abs(angle) > 0.02 else lines
    flipped = _rotate_lines(normalized, math.pi)
    return [normalized, flipped]


def reading_score(data: dict) -> int:
    """Higher means more of the printed card was actually read."""
    score = 4 if data.get("national_id") else 0
    for field in ("issuing_date", "profession_workplace", "gender", "religion", "marital_status", "valid_until"):
        if data.get(field):
            score += 2
    if data.get("husband_name"):
        score += 1
    return score


def structure_back_text(raw_lines: list[dict], national_id: str, *, _oriented: bool = False) -> dict:
    """Map each printed back-of-card row to its own field."""
    if not _oriented:
        best = None
        best_score = -1
        for variant in _orientation_variants(raw_lines):
            parsed = structure_back_text(variant, national_id, _oriented=True)
            score = reading_score(parsed)
            if score > best_score:
                best, best_score = parsed, score
        return best or _empty_back(national_id)

    lines = []
    for raw in raw_lines:
        content = re.sub(r"\s+", " ", (raw.get("content") or "").strip())
        if not content:
            continue
        lines.append({**raw, "content": content})

    national_id = national_id or extract_national_id(lines)
    ordered = sorted(lines, key=lambda item: item["y"] if item.get("y") is not None else 0)
    data = _empty_back(national_id)
    pitch = _estimate_pitch([line for line in ordered if not _is_barcode(line["content"])])

    valid_line = None
    valid_date = None
    consumed = set()
    for line in ordered:
        if not _is_valid_until_line(line["content"]):
            continue
        valid_line = line
        valid_date = _parse_full_date(line["content"])
        consumed.add(id(line))
        break

    if valid_line is not None and valid_date is None:
        below = [
            line for line in ordered
            if line.get("y") is not None and valid_line.get("y") is not None
            and line["y"] > valid_line["y"] and id(line) not in consumed
        ]
        if below:
            nxt = min(below, key=lambda line: line["y"])
            date = _parse_full_date(nxt["content"])
            if date:
                gap = nxt["y"] - valid_line["y"] if valid_line.get("y") is not None else 0
                heights = [valid_line.get("height") or 0, nxt.get("height") or 0]
                if not heights[0] or gap <= max(heights) * 2.2:
                    valid_date = date
                    consumed.add(id(nxt))

    id_line = gender_line = religion_line = marital_line = issuing_line = None
    gender = religion = marital = husband_on_status = None
    unlabeled = []

    for line in ordered:
        if id(line) in consumed:
            continue
        text = line["content"]
        if _is_national_id_line(text, national_id):
            id_line = line
            if issuing_line is None:
                found = _parse_issuing_date(text)
                if found:
                    issuing_line = line
                    data["issuing_date"] = found
            consumed.add(id(line))
            continue
        if _is_serial(text) or _is_barcode(text) or _is_short_number(text):
            continue
        stripped = strip_label(text)
        if _is_header_line(fold_arabic(stripped)) or _is_header_line(fold_arabic(text)):
            continue
        if not stripped:
            continue

        status = _read_status(stripped)
        if status and (status["gender"] or status["religion"] or status["marital"]):
            if status["gender"] and gender is None:
                gender, gender_line = status["gender"], line
            if status["religion"] and religion is None:
                religion, religion_line = status["religion"], line
            if status["marital"] and marital is None:
                marital, marital_line = status["marital"], line
                husband_on_status = status["husband"]
            continue
        issuing = _parse_issuing_date(stripped)
        if issuing and issuing_line is None:
            issuing_line = line
            data["issuing_date"] = issuing
            continue
        if _parse_full_date(stripped) and len(_arabic_letters(stripped)) < 3:
            continue
        unlabeled.append(line)

    if valid_date is None:
        status_floor = None
        for anchor in (gender_line, religion_line, marital_line):
            if anchor and anchor.get("y") is not None:
                status_floor = anchor["y"] if status_floor is None else min(status_floor, anchor["y"])
        bare = []
        for line in ordered:
            if id(line) in consumed or line.get("y") is None:
                continue
            if status_floor is not None and line["y"] <= status_floor:
                continue
            date = _parse_full_date(line["content"])
            if date and len(_arabic_letters(line["content"])) < 3:
                bare.append((line, date))
        if len(bare) == 1:
            valid_line, valid_date = bare[0]

    status_ys = [
        line["y"] for line in (gender_line, religion_line, marital_line)
        if line and line.get("y") is not None
    ]
    if status_ys:
        floor_y = min(status_ys)
    elif valid_line and valid_line.get("y") is not None and pitch:
        floor_y = valid_line["y"] - pitch
    else:
        floor_y = None
    top_ys = [
        line["y"] for line in (id_line, issuing_line)
        if line and line.get("y") is not None
    ]
    top_y = min(top_ys) if top_ys else None

    profession_workplace = _place_profession_workplace(
        unlabeled, floor_y, top_y, pitch
    )
    band_husband = _place_husband(
        unlabeled, [gender_line, religion_line, marital_line], valid_line, pitch
    )
    if _is_female(gender) and _is_married_woman(marital):
        parts = [part for part in (husband_on_status, band_husband) if part]
        husband = _clean_text_field(" ".join(parts)) if parts else None
    else:
        husband = None

    data.update({
        "national_id": national_id or None,
        "profession_workplace": profession_workplace,
        "gender": gender,
        "religion": religion,
        "marital_status": marital,
        "husband_name": husband,
        "valid_until": valid_date,
    })
    return data


def structure_analyze_result(payload: dict) -> dict:
    lines = lines_from_analyze_result(payload)
    return structure_back_text(lines, extract_national_id(lines))


def _blank(value) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def unreadable_field_errors(data: dict) -> dict[str, str]:
    """One message per required field whose own row was not read."""
    errors = {}
    for field in REQUIRED_FIELDS:
        if _blank(data.get(field)):
            data[field] = None
            errors[field] = f"{field} {UNREADABLE}"
    if _is_female(data.get("gender")) and _is_married_woman(data.get("marital_status")):
        if _blank(data.get("husband_name")):
            data["husband_name"] = None
            errors["husband_name"] = f"husband_name {UNREADABLE}"
    elif _blank(data.get("husband_name")):
        data["husband_name"] = None
    return errors
