"""
URL Filter Configuration
Contains patterns and domains that should be filtered out from link extraction
"""

# URL schemes that should be filtered out
FILTERED_SCHEMES = [
    "mailto",      # Email links
    "tel",         # Phone number links
    "javascript",  # JavaScript pseudo-protocols
    "whatsapp",    # WhatsApp deep links
    "data",        # Data URIs
    "file",        # File system links
]

# Domain patterns that should be filtered out (social media, etc.)
FILTERED_DOMAINS = [
    "linkedin.com",
    "x.com",           # Twitter/X
    "twitter.com",
    "facebook.com",
    "instagram.com",
    "youtube.com",
    "tiktok.com",
    "pinterest.com",
    "reddit.com",
    "snapchat.com",
    "discord.com",
    "telegram.org",
]

# Filter out URLs that are empty or whitespace
FILTER_EMPTY = True