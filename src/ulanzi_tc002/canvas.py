import io

CANVAS = (52, 16)


def _fit_frame(im):
    from PIL import Image
    im = im.convert("RGBA")
    scale = min(CANVAS[0] / im.width, CANVAS[1] / im.height)
    width = max(1, round(im.width * scale))
    height = max(1, round(im.height * scale))
    resample = Image.Resampling.NEAREST if scale >= 1 else Image.Resampling.LANCZOS
    resized = im.resize((width, height), resample)
    canvas = Image.new("RGBA", CANVAS, (0, 0, 0, 255))
    canvas.paste(resized, ((CANVAS[0] - width) // 2, (CANVAS[1] - height) // 2), resized)
    return canvas


def fit_to_canvas(data):
    from PIL import Image, ImageSequence, UnidentifiedImageError
    try:
        source = Image.open(io.BytesIO(data))
        source.load()
    except (UnidentifiedImageError, OSError, ValueError) as error:
        raise ValueError("Image must be GIF or PNG") from error
    if source.width < 1 or source.height < 1:
        raise ValueError("Image must be GIF or PNG")
    output = io.BytesIO()
    if getattr(source, "n_frames", 1) > 1:
        frames = []
        durations = []
        for frame in ImageSequence.Iterator(source):
            durations.append(max(20, int(frame.info.get("duration", 100) or 100)))
            frames.append(_fit_frame(frame).convert("RGB"))
        frames[0].save(
            output,
            format="GIF",
            save_all=True,
            append_images=frames[1:],
            duration=durations,
            loop=0,
            disposal=2,
        )
    else:
        _fit_frame(source).save(output, format="PNG")
    return output.getvalue()
