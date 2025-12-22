"""
Central registry for structured output Pydantic models.
Add new models here to make them available for structured extraction.
"""
from typing import Literal, Optional, Type, Dict, Any
from pydantic import BaseModel


class WebsiteContentExtraction(BaseModel):
    """Pydantic model for extracting structured information from website content."""
    page_type: Literal["website", "product"]
    colors: list[str]
    price: Optional[float] = None


class LeadExtraction(BaseModel):
    """Pydantic model for extracting lead/contact information from website visitors."""
    name: str
    email: str
    phone: Optional[str] = None
    description: str  # What they were interested in (in a sentence)


# Registry mapping extraction type keys to their corresponding Pydantic models
STRUCTURED_OUTPUT_MODELS_REGISTRY: Dict[str, Type[BaseModel]] = {
    "website_content": WebsiteContentExtraction,
    "lead": LeadExtraction,
    # Add more models here as needed
    # Example:
    # "product_info": ProductInfoExtraction,
    # "user_profile": UserProfileExtraction,
}


def get_structured_output_model(model_key: str) -> Type[BaseModel]:
    """
    Get the Pydantic model class for the given model key.
    
    Args:
        model_key: The key identifying the structured output model
        
    Returns:
        Type[BaseModel]: The Pydantic model class
        
    Raises:
        ValueError: If the model_key is not found in the registry
    """
    if model_key not in STRUCTURED_OUTPUT_MODELS_REGISTRY:
        available_keys = ", ".join(STRUCTURED_OUTPUT_MODELS_REGISTRY.keys())
        raise ValueError(
            f"Unknown extraction type '{model_key}'. "
            f"Available types: {available_keys}"
        )
    return STRUCTURED_OUTPUT_MODELS_REGISTRY[model_key]


def get_available_model_keys() -> list[str]:
    """
    Get a list of all available model keys in the registry.
    
    Returns:
        list[str]: List of available model keys
    """
    return list(STRUCTURED_OUTPUT_MODELS_REGISTRY.keys())

