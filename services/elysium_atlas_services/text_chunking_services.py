import re
from typing import List
from logging_config import get_logger

logger = get_logger()


def chunk_text_content(
    text_content: str,
    chunk_size: int = 1500,
    chunk_overlap: int = 200
) -> List[str]:
    """
    Production-ready text chunking strategy with sentence-aware splitting and overlap.
    
    This function chunks text content into overlapping segments, attempting to split
    on sentence boundaries to avoid breaking sentences mid-way. Falls back to
    character-based splitting if sentence boundaries are not found.
    
    Args:
        text_content: The text content to chunk
        chunk_size: Maximum characters per chunk (default: 1500)
        chunk_overlap: Number of characters to overlap between chunks (default: 200)
        
    Returns:
        List of text chunks with overlap
        
    Strategy:
        - Chunk size: 1500 characters (optimal for most embedding models)
        - Overlap: 200 characters (~13% overlap for context preservation)
        - Sentence-aware: Tries to split on sentence boundaries (. ! ?)
        - Fallback: Character-based splitting if no sentence boundary found
        - Handles edge cases: empty text, very short text, etc.
    """
    if not text_content or not isinstance(text_content, str):
        logger.warning("Empty or invalid text_content provided for chunking")
        return []
    
    # Strip whitespace
    text_content = text_content.strip()
    
    if len(text_content) == 0:
        return []
    
    # If text is shorter than chunk_size, return as single chunk
    if len(text_content) <= chunk_size:
        return [text_content]
    
    chunks = []
    start = 0
    text_length = len(text_content)
    
    # Validate overlap is less than chunk_size
    if chunk_overlap >= chunk_size:
        logger.warning(f"Overlap ({chunk_overlap}) >= chunk_size ({chunk_size}), reducing overlap to 10% of chunk_size")
        chunk_overlap = chunk_size // 10
    
    while start < text_length:
        # Calculate end position for this chunk
        end = start + chunk_size
        
        # If this is the last chunk, take remaining text
        if end >= text_length:
            chunk = text_content[start:].strip()
            if chunk:  # Only add non-empty chunks
                chunks.append(chunk)
            break
        
        # Try to find a sentence boundary near the end position
        # Look for sentence endings (. ! ?) within the last 20% of the chunk
        search_start = max(start, end - (chunk_size // 5))
        search_end = end
        
        # Pattern to match sentence endings followed by whitespace
        sentence_pattern = r'[.!?]\s+'
        
        # Find the last sentence boundary in the search range
        matches = list(re.finditer(sentence_pattern, text_content[search_start:search_end]))
        
        if matches:
            # Use the last match found
            last_match = matches[-1]
            # Adjust end to include the sentence ending
            end = search_start + last_match.end()
            chunk = text_content[start:end].strip()
        else:
            # No sentence boundary found, try to split on paragraph breaks or line breaks
            # Look for double newlines or single newlines
            paragraph_pattern = r'\n\s*\n'
            line_pattern = r'\n'
            
            # Search backwards from end for paragraph break
            search_text = text_content[search_start:search_end]
            para_match = re.search(paragraph_pattern, search_text)
            line_match = re.search(line_pattern, search_text)
            
            if para_match:
                # Split on paragraph break
                end = search_start + para_match.end()
                chunk = text_content[start:end].strip()
            elif line_match:
                # Split on line break
                end = search_start + line_match.end()
                chunk = text_content[start:end].strip()
            else:
                # Fallback: split at exact position (may break mid-word)
                chunk = text_content[start:end].strip()
        
        # Only add non-empty chunks
        if chunk:
            chunks.append(chunk)
        
        # Move start position forward with overlap
        # Start next chunk from (end - overlap) to maintain context
        start = max(start + 1, end - chunk_overlap)
        
        # Safety check to prevent infinite loops
        if start >= text_length:
            break
    
    # Log chunking statistics
    if chunks:
        logger.info(f"Chunked text into {len(chunks)} chunks (avg size: {sum(len(c) for c in chunks) // len(chunks)} chars)")
    
    return chunks

