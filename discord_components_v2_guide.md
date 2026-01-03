# Discord.py Components V2 Practical Guide

This guide explains how to correctly implement Discord's "Components V2" (introduced in discord.py 2.6) based on practical implementation experience.

## Core Concepts

Components V2 introduces new UI elements like `TextDisplay`, `Container`, and `Separator`, allowing for rich interfaces without using Embeds.

### The Golden Rule: No Embeds
**Critical:** When using V2 components (enabled by `LayoutView` or any V2 component), the message is flagged as `IS_COMPONENTS_V2`.
- You **CANNOT** send `content`, `embed`, `embeds`, `stickers`, or `poll` in the same message.
- The UI components themselves (specifically `TextDisplay` and `Container`) replace the functionality of Embeds.

## 1. View Inheritance

To use V2 components, your view must inherit from `discord.ui.LayoutView` instead of `discord.ui.View`.

```python
from discord import ui

class MyV2View(ui.LayoutView):
    def __init__(self, ...):
        super().__init__(timeout=120)
        # ...
```

## 2. Component Layout & Structure

Discord V2 messages enforce a strict component hierarchy. Top-level components in the `components` list must be valid root types.

### Top-Level Components
These can be added directly to the `LayoutView`:
- `ui.TextDisplay` (Type 10)
- `ui.Container` (Type ?)
- `ui.ActionRow` (Type 1)
- `ui.Separator` (Type ?)

### Standard Components (Buttons, Selects)
Standard components like `ui.Button` (Type 2) and `ui.Select` (Type 3) **MUST** be wrapped in an `ui.ActionRow` (Type 1) when used in a `LayoutView` alongside other V2 components.

**Incorrect (Causes "Invalid Form Body"):**
```python
view.add_item(ui.TextDisplay(content="Title"))
view.add_item(ui.Button(label="Click Me")) # Error: Button cannot be top-level here
```

**Correct:**
```python
view.add_item(ui.TextDisplay(content="Title"))
view.add_item(ui.ActionRow(ui.Button(label="Click Me"))) # Correct: Wrapped in ActionRow
```

## 3. Using `ui.Container` (The "V2 Embed")

To mimic the look and organization of an Embed, use `ui.Container`.

```python
# Create a container with an accent color (like an Embed color)
container = ui.Container(accent_color=discord.Color.green())

# Add components to the container
container.add_item(ui.TextDisplay(content="## Header Text\nSome description..."))
container.add_item(ui.Separator()) # Adds a visual divider
container.add_item(ui.TextDisplay(content="**Field 1**\nValue"))

# Interactive elements inside Container
button = ui.Button(label="Action")
container.add_item(ui.ActionRow(button))

# Add the container to the view
view.add_item(container)
```

## 4. `ui.TextDisplay`

Used for all text content.
- **Content:** Supports Markdown. Max 4000 characters.
- **Usage:** Replaces Embed Title, Description, and Fields.

```python
ui.TextDisplay(content="**Bold Text** and *Italics*")
```

## 5. Migration Checklist

When upgrading a View to V2:
1. Change parent class to `ui.LayoutView`.
2. Remove any usage of `embed=` in `ctx.send()` or `message.edit()`.
3. Move all text content into `ui.TextDisplay` components.
4. Wrap all Buttons and Selects in `ui.ActionRow`.
5. Use `ui.Container` to group related elements and add color.
6. Use `ui.Separator` for dividing sections.

## Example Implementation

```python
class ShopView(ui.LayoutView):
    async def update_components(self):
        self.clear_items()
        
        container = ui.Container(accent_color=discord.Color.blue())
        
        # Header
        container.add_item(ui.TextDisplay(content="## Shop Inventory"))
        
        # Items
        for item in self.items:
            container.add_item(ui.TextDisplay(content=f"**{item.name}** - ${item.price}"))
            container.add_item(ui.Separator())
            
        # Controls
        btn = ui.Button(label="Buy")
        container.add_item(ui.ActionRow(btn))
        
        self.add_item(container)
```
