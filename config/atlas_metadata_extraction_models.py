from typing import Literal, Optional
from pydantic import BaseModel, Field


class AgentWebCatalogEntry(BaseModel):
    """
    Summary-level structured representation of a web or product page
    used for agent routing via agent_web_catalog.
    """

    page_type: Literal["product", "content"] = Field(
        ...,
        description="Type of page: product for product pages, content for non-product pages"
    )

    summary: str = Field(
        ...,
        description=(
            "Concise semantic summary of the page used for embeddings. "
            "For product pages, the summary should naturally include key product details such as "
            "product name, category, price, currency, and other relevant details. "
            "For content pages, summarize the main purpose and information of the page."
        )
    )


    url: str = Field(
        ...,
        description="Canonical URL of the page"
    )

    # --- Product-specific metadata (optional for content pages) ---

    product_name: Optional[str] = Field(
        default=None,
        description="Display name of the product as shown in the store"
    )

    product_id: Optional[str] = Field(
        default=None,
        description="Unique product identifier or SKU (product pages only)"
    )

    category: Optional[str] = Field(
        default=None,
        description="Product category (e.g., Jackets, Shoes)"
    )

    price: Optional[float] = Field(
        default=None,
        description="Product price if available"
    )

    currency: Optional[str] = Field(
        default=None,
        description="Currency code (e.g., INR, USD)"
    )

    is_available: Optional[bool] = Field(
        default=None,
        description=(
            "Indicates product availability. "
            "Set to false only if the page explicitly states the product is out of stock, unavailable, "
            "or cannot be purchased. "
            "If no such indication is present, set to true."
        )
    )
