from image_generator import generate_citation

def create_example_images():
    """Generates and saves example citation images."""
    actions = {
        "ban": ("SomeUser", "Breaking rule #1"),
        "kick": ("AnotherUser", "Spamming chat"),
        "warning": ("Kirin", "Too gay.")
    }

    for action, (member_name, reason) in actions.items():
        print(f"Generating image for {action}...")
        image_buffer = generate_citation(action.capitalize(), member_name, reason)
        with open(f"example_{action}.png", "wb") as f:
            f.write(image_buffer.getvalue())
        print(f"Saved example_{action}.png")

if __name__ == "__main__":
    create_example_images()