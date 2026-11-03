import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from parsing.back_id_fields import (
    _rotate_lines,
    contains_phrase,
    extract_national_id,
    fold_arabic,
    structure_analyze_result,
    structure_back_text,
    unreadable_field_errors,
)


def line(content, y, right=5.2, height=0.28, page_width=6.0):
    return {
        "content": content,
        "y": y,
        "right": right,
        "left": right - 2.0,
        "top": y - height / 2,
        "bottom": y + height / 2,
        "height": height,
        "page_width": page_width,
    }


def card(**overrides):
    """A complete back, rows 0.5 apart. Right edge is shared. Photo text is not."""
    rows = {
        "header": line("جمهورية مصر العربية", 0.4),
        "title": line("بطاقة تحقيق الشخصية", 0.8),
        "serial": line("KA29384711", 1.05, right=2.2),
        "national_id": line("٢٩٥٠١٠١١٢٣٤٥٦٧", 1.3),
        "issuing": line("٢٠٢٠/٠٦", 1.8),
        "profession": line("حاصل على بكالوريوس تجارة", 2.3),
        "company": line("جامعة القاهرة", 2.8),
        "gender": line("ذكر", 3.3),
        "religion": line("مسلم", 3.8),
        "marital": line("أعزب", 4.3),
        "valid": line("البطاقة سارية حتى ٢٠٢٧/٠٦/٠١", 4.8),
        "photo_date": line("01/01/1995", 2.4, right=1.6),
        "barcode": line("99887766554433221100", 5.4, right=3.0),
    }
    rows.update(overrides)
    return [value for value in rows.values() if value is not None]


class PhraseTests(unittest.TestCase):
    def test_word_boundary_blocks_longer_word(self):
        self.assertFalse(contains_phrase(fold_arabic("المنياوي"), fold_arabic("المنيا")))
        self.assertTrue(contains_phrase(fold_arabic("محافظة المنيا"), fold_arabic("المنيا")))

    def test_gender_word_is_not_a_substring(self):
        parsed = structure_back_text([line("مذكرة", 3.3)], "")
        self.assertIsNone(parsed["gender"])


class NationalIdTests(unittest.TestCase):
    def test_arabic_digits(self):
        self.assertEqual(extract_national_id([line("٢٩٥٠١٠١١٢٣٤٥٦٧", 1.0)]), "29501011234567")

    def test_reversed_digits(self):
        reversed_id = "29501011234567"[::-1]
        self.assertEqual(extract_national_id([line(reversed_id, 1.0)]), "29501011234567")


GOUNA = {
    "national_id": "28507011802373",
    "issuing_date": "2025/04",
    "profession_workplace": "مشرف ادارى شركة الجونة للخدمات",
    "gender": "ذكر",
    "religion": "مسلم",
    "marital_status": "متزوج",
    "husband_name": None,
    "valid_until": "2032/04/08",
}


def gouna_card(**overrides):
    """The El Gouna back: status words share a row, job and company share the right edge."""
    def placed(content, y, right):
        return line(content, y, right=right, page_width=10)

    rows = {
        "national_id": placed("٢٨٥٠٧٠١١٨٠٢٣٧٣", 1.0, 8.2),
        "issuing": placed("٢٠٢٥/٠٤", 1.0, 4.6),
        "profession": placed("مشرف ادارى", 1.6, 8.3),
        "company": placed("شركة الجونة للخدمات", 2.2, 8.3),
        "gender": placed("ذكر", 2.8, 8.1),
        "religion": placed("مسلم", 2.8, 5.5),
        "marital": placed("متزوج", 2.8, 3.6),
        "valid": placed("البطاقة سارية حتى ٢٠٣٢/٠٤/٠٨", 3.4, 7.0),
        "marker": placed("١٤", 3.4, 9.2),
        "barcode": placed("998877665544332211", 4.8, 9.0),
    }
    rows.update(overrides)
    return [value for value in rows.values() if value is not None]


class GounaCardTests(unittest.TestCase):
    def test_sample_card(self):
        parsed = structure_back_text(gouna_card(), "")
        self.assertEqual(parsed, GOUNA)
        self.assertEqual(unreadable_field_errors(dict(parsed)), {})

    def test_id_and_issuing_date_on_one_line(self):
        parsed = structure_back_text(gouna_card(
            national_id=line("٢٠٢٥/٠٤ ٢٨٥٠٧٠١١٨٠٢٣٧٣", 1.0, right=8.2, page_width=10),
            issuing=None,
        ), "")
        self.assertEqual(parsed["national_id"], GOUNA["national_id"])
        self.assertEqual(parsed["issuing_date"], GOUNA["issuing_date"])
        self.assertEqual(parsed["profession_workplace"], GOUNA["profession_workplace"])

    def test_status_words_on_one_line_still_split(self):
        parsed = structure_back_text(gouna_card(
            gender=line("ذكر مسلم متزوج", 2.8, right=8.1, page_width=10),
            religion=None,
            marital=None,
        ), "")
        self.assertEqual(parsed["gender"], "ذكر")
        self.assertEqual(parsed["religion"], "مسلم")
        self.assertEqual(parsed["marital_status"], "متزوج")
        self.assertIsNone(parsed["husband_name"])
        self.assertEqual(parsed["profession_workplace"], GOUNA["profession_workplace"])

    def test_marker_and_left_side_text_are_not_fields(self):
        parsed = structure_back_text(gouna_card(
            hologram=line("هولوجرام", 1.9, right=2.2, page_width=10),
        ), "")
        self.assertEqual(parsed, GOUNA)

    def test_watermark_splits_the_national_id(self):
        """The emblem cuts the 14 digits into two OCR fragments on the date row."""
        def placed(content, y, left, right):
            item = line(content, y, right=right, page_width=10)
            item["left"] = left
            return item

        parsed = structure_back_text([
            placed("٢٠٢٣/١١", 1.00, 2.2, 4.0),
            placed("٣٠٠٠١٠", 1.02, 4.6, 6.2),
            placed("٧٠١٠٠٩٩٢", 1.00, 6.5, 8.4),
            placed("حاصل على بكالوريوس تجارة", 1.60, 4.8, 8.4),
            placed("وادارة الاعمال", 2.20, 5.6, 8.4),
            placed("ذكر", 2.80, 7.2, 8.2),
            placed("مسلم", 2.80, 4.6, 5.6),
            placed("أعزب", 2.80, 2.6, 3.6),
            placed("البطاقة سارية حتى ٢٠٣٠/١١/٠٤", 3.40, 2.2, 7.0),
            placed("١", 3.40, 8.5, 9.0),
        ], "")
        self.assertEqual(parsed["national_id"], "30001070100992")
        self.assertEqual(parsed["issuing_date"], "2023/11")
        self.assertEqual(parsed["profession_workplace"], "حاصل على بكالوريوس تجارة وادارة الاعمال")
        self.assertEqual(parsed["gender"], "ذكر")
        self.assertEqual(parsed["religion"], "مسلم")
        self.assertEqual(parsed["marital_status"], "أعزب")
        self.assertIsNone(parsed["husband_name"])
        self.assertEqual(parsed["valid_until"], "2030/11/04")
        self.assertEqual(unreadable_field_errors(dict(parsed)), {})

    def test_upside_down_and_sideways_cards(self):
        for angle in (math.pi, math.pi / 2, -math.pi / 2):
            parsed = structure_back_text(_rotate_lines(gouna_card(), angle), "")
            self.assertEqual(parsed["national_id"], GOUNA["national_id"], angle)
            self.assertEqual(parsed["issuing_date"], GOUNA["issuing_date"], angle)
            self.assertEqual(parsed["profession_workplace"], GOUNA["profession_workplace"], angle)
            self.assertEqual(parsed["gender"], GOUNA["gender"], angle)
            self.assertEqual(parsed["religion"], GOUNA["religion"], angle)
            self.assertEqual(parsed["marital_status"], GOUNA["marital_status"], angle)
            self.assertEqual(parsed["valid_until"], GOUNA["valid_until"], angle)

    def test_missing_gender_keeps_the_words_beside_it(self):
        parsed = structure_back_text(gouna_card(gender=None), "")
        self.assertIsNone(parsed["gender"])
        self.assertEqual(parsed["religion"], "مسلم")
        self.assertEqual(parsed["marital_status"], "متزوج")
        self.assertEqual(parsed["profession_workplace"], GOUNA["profession_workplace"])
        self.assertIn("gender", unreadable_field_errors(dict(parsed)))


class StructureTests(unittest.TestCase):
    def test_full_card(self):
        parsed = structure_back_text(card(), "")
        self.assertEqual(parsed["national_id"], "29501011234567")
        self.assertEqual(parsed["issuing_date"], "2020/06")
        self.assertEqual(parsed["profession_workplace"], "حاصل على بكالوريوس تجارة جامعة القاهرة")
        self.assertEqual(parsed["gender"], "ذكر")
        self.assertEqual(parsed["religion"], "مسلم")
        self.assertEqual(parsed["marital_status"], "أعزب")
        self.assertIsNone(parsed["husband_name"])
        self.assertEqual(parsed["valid_until"], "2027/06/01")
        self.assertEqual(unreadable_field_errors(dict(parsed)), {})

    def test_one_job_line_fills_the_same_field(self):
        parsed = structure_back_text(card(company=None), "")
        self.assertEqual(parsed["profession_workplace"], "حاصل على بكالوريوس تجارة")
        self.assertEqual(parsed["gender"], "ذكر")
        self.assertEqual(unreadable_field_errors(dict(parsed)), {})

    def test_two_job_lines_are_one_field(self):
        parsed = structure_back_text(card(
            profession=line("حاصل على بكالوريوس", 2.30),
            company=line("تجارة شعبة محاسبة", 2.52),
        ), "")
        self.assertEqual(parsed["profession_workplace"], "حاصل على بكالوريوس تجارة شعبة محاسبة")

    def test_one_word_second_row_stays_in_the_same_field(self):
        parsed = structure_back_text(card(
            profession=line("عبد الرحمن محمد", 2.3),
            company=line("القاهرة", 2.8),
        ), "")
        self.assertEqual(parsed["profession_workplace"], "عبد الرحمن محمد القاهرة")

    def test_missing_gender_is_not_filled_by_the_line_below(self):
        parsed = structure_back_text(card(gender=None), "")
        self.assertIsNone(parsed["gender"])
        self.assertEqual(parsed["profession_workplace"], "حاصل على بكالوريوس تجارة جامعة القاهرة")
        self.assertEqual(parsed["religion"], "مسلم")
        errors = unreadable_field_errors(dict(parsed))
        self.assertIn("gender", errors)
        self.assertNotIn("profession_workplace", errors)
        self.assertTrue(errors["gender"].endswith(
            "can't be read. Please upload a better quality image or a clearer image."
        ))

    def test_only_the_workplace_line_still_fills_the_field(self):
        parsed = structure_back_text(card(profession=None), "")
        self.assertEqual(parsed["profession_workplace"], "جامعة القاهرة")
        self.assertEqual(unreadable_field_errors(dict(parsed)), {})

    def test_photo_date_is_not_issuing_or_expiry(self):
        parsed = structure_back_text(card(), "")
        self.assertEqual(parsed["issuing_date"], "2020/06")
        self.assertEqual(parsed["valid_until"], "2027/06/01")

    def test_header_and_serial_are_not_profession(self):
        parsed = structure_back_text(card(profession=None, company=None), "")
        self.assertIsNone(parsed["profession_workplace"])

    def test_day_first_expiry_on_the_next_line(self):
        parsed = structure_back_text(card(
            valid=line("البطاقة سارية حتى", 4.8),
            expiry_value=line("01/06/2027", 5.15),
        ), "")
        self.assertEqual(parsed["valid_until"], "2027/06/01")

    def test_arabic_digit_expiry_on_the_next_line(self):
        parsed = structure_back_text(card(
            valid=line("البطاقة سارية حتى", 4.8),
            expiry_value=line("٠١/٠٦/٢٠٢٧", 5.15),
        ), "")
        self.assertEqual(parsed["valid_until"], "2027/06/01")

    def test_husband_tucked_under_the_status_row(self):
        """متزوجة sits on the same row as أنثى and مسلمة. The name is the next line."""
        def placed(content, y, left, right):
            item = line(content, y, right=right, page_width=10)
            item["left"] = left
            return item

        parsed = structure_back_text([
            placed("٢٠٢٤/٠٥", 1.00, 2.0, 3.8),
            placed("٢٧١٠٤٠٧٠١٠٠٢٦٨", 1.00, 5.2, 8.4),
            placed("حاصلة على ليسانس ألسن", 1.55, 4.4, 8.4),
            placed("أنثى", 2.20, 7.4, 8.3),
            placed("مسلمة", 2.22, 5.0, 6.2),
            placed("متزوجة", 2.28, 2.4, 3.8),
            placed("يحيى السيد مصطفى الدقاق", 2.55, 2.2, 6.4),
            placed("البطاقة سارية حتى ٢٠٣١/٠٥/١٨", 3.15, 2.0, 7.2),
            placed("١", 3.15, 8.4, 8.8),
        ], "")
        self.assertEqual(parsed["national_id"], "27104070100268")
        self.assertEqual(parsed["issuing_date"], "2024/05")
        self.assertEqual(parsed["profession_workplace"], "حاصلة على ليسانس ألسن")
        self.assertEqual(parsed["gender"], "أنثى")
        self.assertEqual(parsed["religion"], "مسلمة")
        self.assertEqual(parsed["marital_status"], "متزوجة")
        self.assertEqual(parsed["husband_name"], "يحيى السيد مصطفى الدقاق")
        self.assertEqual(parsed["valid_until"], "2031/05/18")
        self.assertEqual(unreadable_field_errors(dict(parsed)), {})

    def test_husband_name_split_across_two_lines_under_status(self):
        def placed(content, y, left, right):
            item = line(content, y, right=right, page_width=10)
            item["left"] = left
            return item

        parsed = structure_back_text([
            placed("٢٠٢٤/٠٥", 1.00, 2.0, 3.8),
            placed("٢٧١٠٤٠٧٠١٠٠٢٦٨", 1.00, 5.2, 8.4),
            placed("حاصلة على ليسانس ألسن", 1.55, 4.4, 8.4),
            placed("أنثى", 2.20, 7.4, 8.3),
            placed("مسلمة", 2.22, 5.0, 6.2),
            placed("متزوجة", 2.28, 2.4, 3.8),
            placed("يحيى السيد", 2.62, 4.2, 6.4),
            placed("مصطفى الدقاق", 2.82, 4.4, 6.2),
            placed("البطاقة سارية حتى ٢٠٣١/٠٥/١٨", 3.15, 2.0, 7.2),
        ], "")
        self.assertEqual(parsed["husband_name"], "يحيى السيد مصطفى الدقاق")
        self.assertEqual(parsed["profession_workplace"], "حاصلة على ليسانس ألسن")
        self.assertEqual(parsed["valid_until"], "2031/05/18")

    def test_married_woman_husband_on_its_own_row(self):
        parsed = structure_back_text(card(
            gender=line("أنثى", 3.3),
            marital=line("متزوجة", 4.3),
            husband=line("أحمد محمد علي", 4.8),
            valid=line("البطاقة سارية حتى ٢٠٣٠/٠١/١٥", 5.3),
        ), "")
        self.assertEqual(parsed["gender"], "أنثى")
        self.assertEqual(parsed["marital_status"], "متزوجة")
        self.assertEqual(parsed["husband_name"], "أحمد محمد علي")
        self.assertEqual(parsed["valid_until"], "2030/01/15")
        self.assertEqual(unreadable_field_errors(dict(parsed)), {})

    def test_husband_on_the_marital_line(self):
        parsed = structure_back_text(card(
            gender=line("أنثى", 3.3),
            marital=line("الحالة الاجتماعية متزوجة أحمد محمد علي", 4.3),
        ), "")
        self.assertEqual(parsed["marital_status"], "متزوجة")
        self.assertEqual(parsed["husband_name"], "أحمد محمد علي")

    def test_male_extra_line_is_not_stored_as_husband(self):
        parsed = structure_back_text(card(
            note=line("بدون", 4.8),
            valid=line("البطاقة سارية حتى ٢٠٢٧/٠٦/٠١", 5.3),
        ), "")
        self.assertIsNone(parsed["husband_name"])
        self.assertEqual(parsed["valid_until"], "2027/06/01")
        self.assertEqual(unreadable_field_errors(dict(parsed)), {})

    def test_married_woman_without_husband_row_is_an_error(self):
        parsed = structure_back_text(card(
            gender=line("أنثى", 3.3),
            marital=line("متزوجة", 4.3),
        ), "")
        self.assertIsNone(parsed["husband_name"])
        errors = unreadable_field_errors(dict(parsed))
        self.assertIn("husband_name", errors)
        self.assertNotIn("profession_workplace", errors)

    def test_stray_line_far_from_a_slot_is_dropped(self):
        parsed = structure_back_text(card(
            stray=line("نص عشوائي بعيد", 0.2),
        ), "")
        self.assertEqual(parsed["profession_workplace"], "حاصل على بكالوريوس تجارة جامعة القاهرة")
        self.assertNotIn("نص عشوائي بعيد", parsed.values())


class AnalyzeResultTests(unittest.TestCase):
    def test_document_intelligence_payload(self):
        def polygon(y, right=5.2):
            top, bottom = y - 0.14, y + 0.14
            left = right - 2.0
            return [left, top, right, top, right, bottom, left, bottom]

        payload = {
            "status": "succeeded",
            "analyzeResult": {
                "pages": [{
                    "width": 6.0,
                    "height": 8.0,
                    "lines": [
                        {"content": "٢٩٥٠١٠١١٢٣٤٥٦٧", "polygon": polygon(1.3)},
                        {"content": "2020/06", "polygon": polygon(1.8)},
                        {"content": "موظف", "polygon": polygon(2.3)},
                        {"content": "النوع ذكر", "polygon": polygon(3.3)},
                        {"content": "الديانة مسلم", "polygon": polygon(3.8)},
                        {"content": "الحالة الاجتماعية أعزب", "polygon": polygon(4.3)},
                        {"content": "البطاقة سارية حتى 2027/06/01", "polygon": polygon(4.8)},
                        {"content": "1995/01/01", "polygon": polygon(2.5, right=1.5)},
                    ],
                }]
            },
        }
        parsed = structure_analyze_result(payload)
        self.assertEqual(parsed["national_id"], "29501011234567")
        self.assertEqual(parsed["issuing_date"], "2020/06")
        self.assertEqual(parsed["profession_workplace"], "موظف")
        self.assertEqual(parsed["gender"], "ذكر")
        self.assertEqual(parsed["religion"], "مسلم")
        self.assertEqual(parsed["marital_status"], "أعزب")
        self.assertEqual(parsed["valid_until"], "2027/06/01")
        self.assertEqual(unreadable_field_errors(dict(parsed)), {})


if __name__ == "__main__":
    unittest.main()
