DEFAULT_GUILD = {
    # Core Settings
    "support_roles": [],  # Role ids that have access to all tickets
    "blacklist": [],  # User ids that cannot open any tickets
    "max_tickets": 1,  # Max amount of tickets a user can have open at a time of any kind
    "inactive": 0,  # Auto close tickets with X hours of inactivity (0 = disabled)
    "overview_channel": 0,  # Overview of open tickets
    "overview_msg": 0,  # Message id of the overview info
    "overview_mention": False,  # Whether the channel names are displayed or the name
    "dm": False,  # Whether to DM the user when their ticket is closed
    "user_can_rename": False,  # Ticket opener can rename their ticket channel
    "user_can_close": True,  # Ticket opener can close their own ticket
    "user_can_manage": False,  # Ticket opener can add other users to their ticket
    "suspended_msg": None,  # If not None, user will be presented with this message when trying to open a ticket
    
    # Panel Settings (Flattened)
    "category_id": 0,
    "channel_id": 0,
    "message_id": 0,
    "button_text": "Open a Ticket",
    "button_color": "blue",
    "button_emoji": None,
    "ticket_messages": [],
    "ticket_name": None,
    "log_channel": 0,
    "modal": {},
    "modal_title": "",
    "ticket_num": 1,
    
    # Legacy / Optional
    "required_roles": [],
    "close_reason": True,
    
    # Active Tickets
    "opened": {},  # All opened tickets {user_id: {channel_id: ticket_data}}
}

MODAL_SCHEMA = {
    "label": "",  # <Required>
    "style": "short",  # <Required>
    "placeholder": None,  # (Optional)
    "default": None,  # (Optional)
    "required": True,  # (Optional)
    "min_length": None,  # (Optional)
    "max_length": None,  # (Optional)
    "answer": None,  # (Optional)
}

TICKET_MESSAGE_SCHEMA = {
    "title": None,  # (Optional) Embed title
    "desc": "",  # <Required> Embed description
    "footer": None,  # (Optional) Embed footer
    "color": None,  # (Optional) Embed color as hex int (e.g., 0xFF0000 for red)
    "image": None,  # (Optional) Embed image URL
}

OPENED_TICKET_SCHEMA = {
    "opened": "datetime",
    "pfp": "url or None",
    "logmsg": "message ID or None",
    "answers": {"question": "answer"},
    "has_response": bool,
    "message_id": "Message ID of first message in the ticket sent from the bot",
    "overview_msg": "Ticket overview message ID (Optional)",
}
