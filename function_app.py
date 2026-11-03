import os
import io
import json
import logging
import time
from contextlib import contextmanager

import azure.functions as func
import pyodbc
import requests

from parsing.back_id_fields import (
    OUTPUT_FIELDS,
    lines_from_analyze_result,
    reading_score,
    structure_back_text,
    unreadable_field_errors,
)

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)

try:
    AZURE_DOC_INTEL_ENDPOINT = os.environ["AZURE_DOC_INTEL_ENDPOINT"].rstrip("/")
    AZURE_DOC_INTEL_KEY = os.environ["AZURE_DOC_INTEL_KEY"]
    sql_connect_str = os.environ["SqlConnectionString"]
except KeyError as e:
    raise Exception(f"ERROR: Missing Application Setting {e}") from e

DI_API_VERSION = "2024-11-30"
DI_MODEL_ID = os.getenv("DI_MODEL_ID", "prebuilt-read")
DI_FEATURES = os.getenv("DI_FEATURES", "").strip()
DI_POLL_INTERVAL = int(os.getenv("DI_POLL_INTERVAL_MS", "400")) / 1000
DI_TIMEOUT_S = 30.0
IMAGE_MAX_SIDE_PX = int(os.getenv("IMAGE_MAX_SIDE_PX") or 0)

di_session = requests.Session()
di_session.headers.update({"Ocp-Apim-Subscription-Key": AZURE_DOC_INTEL_KEY})


@contextmanager
def timed(label: str, bag: dict):
    start = time.perf_counter()
    try:
        yield
    finally:
        bag[label] = round((time.perf_counter() - start) * 1000, 1)


def analyze(doc_bytes: bytes, model_id: str, interval: float, timeout: float = DI_TIMEOUT_S) -> dict:
    deadline = time.monotonic() + timeout
    url = (f"{AZURE_DOC_INTEL_ENDPOINT}/documentintelligence/documentModels/"
           f"{model_id}:analyze?api-version={DI_API_VERSION}")
    if DI_FEATURES:
        url += f"&features={DI_FEATURES}"

    while True:
        resp = di_session.post(
            url,
            data=doc_bytes,
            headers={"Content-Type": "application/octet-stream"},
            timeout=timeout,
        )
        if resp.status_code != 429:
            break
        if time.monotonic() >= deadline:
            raise TimeoutError("DI analyze request throttled until timeout")
        time.sleep(float(resp.headers.get("Retry-After", 1)))
    if resp.status_code != 202:
        raise RuntimeError(f"DI analyze request failed ({resp.status_code}): {resp.text}")
    operation_url = resp.headers["Operation-Location"]

    while True:
        time.sleep(interval)
        if time.monotonic() >= deadline:
            raise TimeoutError(f"DI analyze did not finish within {timeout}s")
        resp = di_session.get(operation_url, timeout=timeout)
        if resp.status_code == 429:
            time.sleep(float(resp.headers.get("Retry-After", 1)))
            continue
        resp.raise_for_status()
        body = resp.json()
        status = body.get("status")
        if status == "succeeded":
            return body["analyzeResult"]
        if status in ("failed", "canceled"):
            raise RuntimeError(f"DI analyze {status}: {json.dumps(body.get('error'))}")


def maybe_resize(image_bytes: bytes) -> bytes:
    """Honor the phone's EXIF orientation, then shrink only when asked."""
    if not image_bytes or image_bytes[:4] == b"%PDF":
        return image_bytes
    from PIL import Image, ImageOps
    with Image.open(io.BytesIO(image_bytes)) as img:
        orientation = 1
        exif = img.getexif()
        if exif:
            orientation = exif.get(274, 1) or 1
        needs_resize = bool(IMAGE_MAX_SIDE_PX) and max(img.size) > IMAGE_MAX_SIDE_PX
        if orientation == 1 and not needs_resize:
            return image_bytes
        img = ImageOps.exif_transpose(img)
        if needs_resize:
            img.thumbnail((IMAGE_MAX_SIDE_PX, IMAGE_MAX_SIDE_PX))
        out = io.BytesIO()
        img.convert("RGB").save(out, format="JPEG", quality=92)
        return out.getvalue()


def _rotate_image(image_bytes: bytes, degrees_clockwise: int) -> bytes:
    from PIL import Image
    with Image.open(io.BytesIO(image_bytes)) as img:
        rotated = img.convert("RGB").rotate(-degrees_clockwise, expand=True)
        out = io.BytesIO()
        rotated.save(out, format="JPEG", quality=92)
        return out.getvalue()


def save_back_data_to_db(data: dict, conn_str: str):
    sql_insert_query = """
        INSERT INTO dbo.EgyptianBackIDsData (
            national_id_back, issuing_date_back, profession_workplace_back,
            gender_back, religion_back, marital_status_back, husband_name_back, valid_until_back
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?);
    """
    values_to_insert = (
        data.get("national_id"), data.get("issuing_date"), data.get("profession_workplace"),
        data.get("gender"), data.get("religion"), data.get("marital_status"),
        data.get("husband_name"), data.get("valid_until"),
    )
    try:
        logging.info("Connecting to the database to save ID back data.")
        with pyodbc.connect(conn_str) as cnxn:
            with cnxn.cursor() as cursor:
                cursor.execute(sql_insert_query, values_to_insert)
                cnxn.commit()
        logging.info("Successfully saved ID back data to the database.")
    except pyodbc.Error as db_err:
        logging.error(f"Database Error: Failed to save ID back data. Error: {db_err}", exc_info=True)
        raise


def _read_image(image_data: bytes) -> tuple[list[dict], dict]:
    result = analyze(image_data, DI_MODEL_ID, DI_POLL_INTERVAL)
    lines = lines_from_analyze_result(result)
    return lines, structure_back_text(lines, "")


def extract_text_from_id(image_data: bytes) -> tuple[list[dict], str]:
    """Read the card. If the first pass is missing fields, try the other rotations."""
    blobs = [image_data]
    best_lines: list[dict] = []
    best_id = ""
    best_score = -1
    index = 0
    while index < len(blobs):
        lines, parsed = _read_image(blobs[index])
        score = reading_score(parsed)
        if score > best_score:
            best_lines = lines
            best_id = parsed.get("national_id") or ""
            best_score = score
        if best_score >= 14:
            break
        if index == 0 and image_data[:4] != b"%PDF":
            for angle in (90, 180, 270):
                try:
                    blobs.append(_rotate_image(image_data, angle))
                except Exception:
                    logging.warning("Could not rotate the image by %s degrees", angle, exc_info=True)
            if len(blobs) > 1:
                logging.info("First read scored %s. Trying rotated copies.", best_score)
        index += 1
    return best_lines, best_id


def _json_response(payload: dict, status_code: int) -> func.HttpResponse:
    return func.HttpResponse(
        body=json.dumps(payload, indent=4, ensure_ascii=False),
        status_code=status_code,
        mimetype="application/json",
    )


@app.route(route="process_back_id")
@app.queue_output(arg_name="msg", queue_name="owest-makadi-back-id-to-save", connection="AzureWebJobsStorage")
def process_id_and_queue(req: func.HttpRequest, msg: func.Out[str]) -> func.HttpResponse:
    logging.info("Python HTTP trigger function processed a request.")
    timings = {}
    try:
        image_data = req.get_body()
        if not image_data:
            return func.HttpResponse("Please pass image data in the request body.", status_code=400)

        with timed("preprocess", timings):
            image_data = maybe_resize(image_data)

        with timed("di_analyze", timings):
            raw_lines, national_id = extract_text_from_id(image_data)

        with timed("structure", timings):
            if raw_lines:
                structured = structure_back_text(raw_lines, national_id)
            else:
                structured = {field: None for field in OUTPUT_FIELDS}

        errors = unreadable_field_errors(structured)
        if errors:
            structured["errors"] = errors
            logging.info("Unreadable fields: %s", ", ".join(errors))
            return _json_response(structured, 422)

        msg.set(json.dumps(structured, ensure_ascii=False))
        return _json_response(structured, 200)
    except Exception as e:
        logging.error(f"Unhandled error in process_id_and_queue: {e}", exc_info=True)
        return func.HttpResponse("An unexpected error occurred.", status_code=500)
    finally:
        logging.info("timing_ms %s", timings)


@app.queue_trigger(arg_name="msg", queue_name="owest-makadi-back-id-to-save", connection="AzureWebJobsStorage")
def save_data_from_queue(msg: func.QueueMessage) -> None:
    logging.info("Python Queue trigger function started processing a message.")
    timings = {}
    try:
        data = json.loads(msg.get_body().decode("utf-8"))
        logging.info("Received data from queue for National ID: %s", data.get("national_id"))
        with timed("sql_write", timings):
            save_back_data_to_db(data, sql_connect_str)
        logging.info("Successfully saved data for National ID: %s", data.get("national_id"))
    except Exception as e:
        logging.error(f"Error processing queue message: {e}", exc_info=True)
        raise
    finally:
        logging.info("timing_ms %s", timings)
