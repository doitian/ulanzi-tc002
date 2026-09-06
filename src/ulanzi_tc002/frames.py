import base64
import binascii

from ulanzi_tc002.colors import resolve_color

MAX_IMAGE_BYTES = 2 * 1024 * 1024


def blank_frame():
    return {"duration": 10, "text": [], "image": [],
            "draw": [{"df": [0, 0, 52, 16, "#000000"]}]}


def text_frame(text, color="#FFFFFF", duration=10):
    if not text or any(not 32 <= ord(c) <= 126 for c in text):
        raise ValueError("Text must contain printable ASCII; use a bitmap frame for other scripts.")
    color = resolve_color(color)
    if duration <= 0:
        raise ValueError("Duration must be positive")
    element = {"content": text.upper(), "fontHeight": 10, "y": 3,
               "color": color, "rect": [0, 0, 52, 16], "x": 0}
    if len(text) <= 8:
        element.update(x=-1000, align="center")
    return {"duration": duration, "text": [element]}


def scroll_frames(text, color):
    frame = text_frame(text, color)
    element = frame["text"][0]
    width = len(element["content"]) * 6
    if width <= 52:
        yield frame
        return
    element.pop("align", None)
    from ulanzi_tc002.ansi_text import marquee_offsets
    for copies in marquee_offsets(width):
        elements = []
        for x in copies:
            if x < 52 and x + width > 0:
                skipped = max(0, -x // 6)
                content = element["content"][skipped:skipped + 10]
                elements.append(dict(element, content=content, x=x + skipped * 6))
        yield {"duration": 10, "text": elements}


def image_kind(data):
    if data.startswith(b"GIF8"):
        return "gif"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    raise ValueError("Image must be GIF or PNG")


def image_data_uri(data):
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError("Image cannot exceed 2 MiB")
    kind = image_kind(data)
    return f"data:image/{kind};base64,{base64.b64encode(data).decode('ascii')}"


def _b64decode(payload):
    pad = "=" * (-len(payload) % 4)
    try:
        return base64.b64decode(payload + pad, validate=True)
    except binascii.Error as error:
        raise ValueError("Image is not valid base64") from error


def parse_image(value):
    if not isinstance(value, str) or not value:
        raise ValueError("Image must be a data URI or base64 string")
    value = "".join(value.split())
    if value.startswith("data:"):
        header, separator, payload = value.partition(",")
        if separator != "," or ";base64" not in header.lower():
            raise ValueError("Image data URI must be base64")
        data = _b64decode(payload)
    else:
        data = _b64decode(value)
    return image_data_uri(data)


def image_frame(image, duration=10):
    if duration <= 0:
        raise ValueError("Duration must be positive")
    return {"duration": duration, "image": [{"data": parse_image(image), "position": [0, 0]}]}


def publish(device, app, frame):
    from ulanzi_tc002.http import request
    result = request(
        f"http://{device}/api/custom?name={app}",
        method="POST",
        json_body=frame,
        timeout=10,
    )
    if not isinstance(result, dict) or result.get("code") != 200:
        raise ValueError(f"Device rejected frame: {result}")
    return result


def unpublish(device, app, frame=None):
    from ulanzi_tc002.http import request
    result = request(
        f"http://{device}/api/custom?name={app}",
        method="POST",
        json_body={},
        timeout=10,
    )
    if result is None:
        return {"code": 200}
    if not isinstance(result, dict) or result.get("code") != 200:
        raise ValueError(f"Device rejected delete: {result}")
    return result
