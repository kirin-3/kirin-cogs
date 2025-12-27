from PIL import Image, ImageDraw, ImageFont
import io

def generate_citation(action: str, member_name: str, reason: str):
    """Generate a 'papers, please' style citation image."""
    # Load the base image
    try:
        image = Image.open("base.png").convert("RGBA")
    except FileNotFoundError:
        # Fallback if base image is missing
        width, height = 400, 200
        bg_color = (240, 230, 230)
        image = Image.new("RGB", (width, height), bg_color)

    draw = ImageDraw.Draw(image)

    # Load the font
    try:
        font = ImageFont.truetype("04B_03__.TTF", 16)
    except IOError:
        font = ImageFont.load_default()

    # Draw the text
    text_color = (138, 206, 244)
    draw.text((30, 55), f"Protocol violation.", font=font, fill=text_color)
    draw.text((30, 80), f"User: {member_name}", font=font, fill=text_color)
    draw.text((30, 115), f"Reason: {reason}", font=font, fill=text_color)
    draw.text((120, 165), f"{action.upper()} ISSUED", font=font, fill=text_color)


    # Save the image to a bytes buffer
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer