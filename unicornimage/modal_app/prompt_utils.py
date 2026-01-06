import torch
import logging

# Configure logging
logger = logging.getLogger(__name__)

MAX_TOKEN_LENGTH = 77

def encode_prompt_chunked(
    pipe,
    prompt: str,
    negative_prompt: str,
    device: "torch.device", # Use string literal for type hint
    batch_size: int,
    max_length: int = MAX_TOKEN_LENGTH
):
    """
    Encodes positive and negative prompts using token-based chunking and concatenates embeddings.
    Mimics Automatic1111's approach to handling long prompts by concatenating token embeddings.
    Handles dual text encoders for SDXL and batching.
    """
    # Get the tokenizers and text encoders
    tokenizer, tokenizer_2 = pipe.tokenizer, pipe.tokenizer_2
    text_encoder, text_encoder_2 = pipe.text_encoder, pipe.text_encoder_2
    
    # Get the hidden size and projection dim for output shapes
    # hidden_size_1 = text_encoder.config.hidden_size
    # hidden_size_2 = text_encoder_2.config.hidden_size
    # combined_hidden_size = hidden_size_1 + hidden_size_2

    # --- Tokenize Original Prompts (without truncation/padding initially) ---
    # Get raw token IDs for the full prompts
    # Use add_special_tokens=False to get just the prompt tokens
    pos_input_ids_1_raw = tokenizer(prompt, add_special_tokens=False, truncation=False, return_tensors="pt").input_ids[0].tolist()
    pos_input_ids_2_raw = tokenizer_2(prompt, add_special_tokens=False, truncation=False, return_tensors="pt").input_ids[0].tolist()
    neg_input_ids_1_raw = tokenizer(negative_prompt or "", add_special_tokens=False, truncation=False, return_tensors="pt").input_ids[0].tolist() # Handle empty string
    neg_input_ids_2_raw = tokenizer_2(negative_prompt or "", add_special_tokens=False, truncation=False, return_tensors="pt").input_ids[0].tolist() # Handle empty string


    # Determine total max length across all tokenizations
    # This is the effective length of the prompt content needing to be covered by chunks
    total_max_len = max(
        len(pos_input_ids_1_raw),
        len(pos_input_ids_2_raw),
        len(neg_input_ids_1_raw),
        len(neg_input_ids_2_raw),
    )

    # Account for BOS/EOS tokens in each chunk
    # A standard chunk includes [BOS]...[EOS]. The prompt content fits in MAX_TOKEN_LENGTH - 2 slots.
    # Use a safer calculation for num special tokens if available, otherwise default to 2
    num_special_tokens = tokenizer.num_special_tokens_to_add(pair=False) if hasattr(tokenizer, 'num_special_tokens_to_add') else 2
    effective_chunk_size = max_length - num_special_tokens

    if effective_chunk_size <= 0:
            raise ValueError(f"Effective chunk size is too small or zero: {effective_chunk_size}. Check MAX_TOKEN_LENGTH and tokenizer special tokens.")

    # Calculate number of chunks needed based on the total length
    num_chunks = (total_max_len + effective_chunk_size - 1) // effective_chunk_size


    # --- Handle Non-Chunking Case ---
    # If total length fits within one effective chunk (e.g., <= 75 prompt tokens),
    # then the standard pipeline encode_prompt is sufficient and handles batching.
    if num_chunks <= 1:
        logger.info("Prompt fits within max effective token length, using standard encoding.")
        # Use the pipeline's internal encoding method which handles batching and dual encoders
        # Important: We're not passing batch_size, as that will be handled separately
        prompt_embeds, negative_prompt_embeds, pooled_prompt_embeds, negative_pooled_prompt_embeds = pipe.encode_prompt(
            prompt=prompt,
            negative_prompt=negative_prompt,
            device=device,
            num_images_per_prompt=1,  # Changed from batch_size to 1
            do_classifier_free_guidance=True, # Assume CFG
            # Add other relevant args like clean_caption if needed
        )
        return prompt_embeds, negative_prompt_embeds, pooled_prompt_embeds, negative_pooled_prompt_embeds


    # --- Handle Token-Based Chunking Case (Mimics A1111) ---
    logger.info(f"Prompt requires token-based chunking into {num_chunks} chunks.")

    # --- NEW: Variables to store embeddings for concatenation ---
    final_prompt_embeds = None
    final_negative_prompt_embeds = None
    
    # --- NEW: Variables to store first chunk's pooled output ---
    first_chunk_pooled_prompt_embeds = None
    first_chunk_negative_pooled_prompt_embeds = None

    # Get pad token IDs safely (EOS is often reused as PAD for CLIP)
    pad_token_id_1 = tokenizer.pad_token_id if tokenizer.pad_token_id is not None else tokenizer.eos_token_id
    pad_token_id_2 = tokenizer_2.pad_token_id if tokenizer_2.pad_token_id is not None else tokenizer_2.eos_token_id

    # Ensure encoders are in evaluation mode
    text_encoder.eval()
    text_encoder_2.eval()

    with torch.no_grad():
        for i in range(num_chunks):
            # Calculate slice indices for the original raw token ID lists
            # Include overlap between chunks (5 tokens) except for the first chunk
            overlap_tokens = 5 if i > 0 else 0
            start_idx = max(0, i * effective_chunk_size - overlap_tokens)
            end_idx = min(start_idx + effective_chunk_size, total_max_len) # Slice up to total_max_len

            # --- Process Positive Prompt Chunk ---
            # Get the slice of raw tokens for this chunk
            pos_chunk_ids_1_slice = pos_input_ids_1_raw[start_idx:end_idx]
            pos_chunk_ids_2_slice = pos_input_ids_2_raw[start_idx:end_idx]

            # Add special tokens ([BOS]...[EOS]) and pad to max_length (77) for Encoder 1
            pos_chunk_ids_1_padded = [tokenizer.bos_token_id] + pos_chunk_ids_1_slice + [tokenizer.eos_token_id]
            pos_chunk_attention_mask_1 = [1] * len(pos_chunk_ids_1_padded)
            padding_length_1 = max_length - len(pos_chunk_ids_1_padded)
            if padding_length_1 > 0:
                pos_chunk_ids_1_padded += [pad_token_id_1] * padding_length_1
                pos_chunk_attention_mask_1 += [0] * padding_length_1
            pos_chunk_ids_1_tensor = torch.tensor([pos_chunk_ids_1_padded], device=device)
            pos_chunk_attention_mask_1_tensor = torch.tensor([pos_chunk_attention_mask_1], device=device)


            # Add special tokens ([BOS]...[EOS]) and pad to max_length (77) for Encoder 2
            pos_chunk_ids_2_padded = [tokenizer_2.bos_token_id] + pos_chunk_ids_2_slice + [tokenizer_2.eos_token_id]
            pos_chunk_attention_mask_2 = [1] * len(pos_chunk_ids_2_padded)
            padding_length_2 = max_length - len(pos_chunk_ids_2_padded)
            if padding_length_2 > 0:
                pos_chunk_ids_2_padded += [pad_token_id_2] * padding_length_2
                pos_chunk_attention_mask_2 += [0] * padding_length_2
            pos_chunk_ids_2_tensor = torch.tensor([pos_chunk_ids_2_padded], device=device)
            pos_chunk_attention_mask_2_tensor = torch.tensor([pos_chunk_attention_mask_2], device=device)


            # Encode chunk with Text Encoder 1
            pos_chunk_embeds_1 = text_encoder(
                pos_chunk_ids_1_tensor,
                attention_mask=pos_chunk_attention_mask_1_tensor,
                output_hidden_states=True,
            ).hidden_states[-2] # Second to last layer

            # Encode chunk with Text Encoder 2
            pos_chunk_output_2 = text_encoder_2(
                pos_chunk_ids_2_tensor,
                attention_mask=pos_chunk_attention_mask_2_tensor,
                output_hidden_states=True,
                return_dict=True,
            )
            pos_chunk_embeds_2 = pos_chunk_output_2.hidden_states[-2] # Second to last layer
            
            # Access text_embeds for the pooled output from CLIPTextModelWithProjection
            if hasattr(pos_chunk_output_2, 'text_embeds'):
                # CLIPTextModelWithProjection provides text_embeds
                pos_pooled_embeds_2 = pos_chunk_output_2.text_embeds
            elif hasattr(pos_chunk_output_2, 'pooled_output'):
                # Legacy access for backward compatibility
                pos_pooled_embeds_2 = pos_chunk_output_2.pooled_output
            else:
                # Fallback - use the last hidden state's first token ([CLS]/[BOS]) as pooled representation
                logger.warning("No pooled embeddings found, falling back to first token of last hidden state")
                pos_pooled_embeds_2 = pos_chunk_output_2.last_hidden_state[:, 0]


            # Concatenate hidden states from both encoders for this chunk
            # Ensure tensors have the same sequence length before concatenating
            seq_len = max(pos_chunk_embeds_1.shape[1], pos_chunk_embeds_2.shape[1])
            if pos_chunk_embeds_1.shape[1] != seq_len:
                pos_chunk_embeds_1 = torch.nn.functional.pad(pos_chunk_embeds_1, (0, 0, 0, seq_len - pos_chunk_embeds_1.shape[1]), value=0)
            if pos_chunk_embeds_2.shape[1] != seq_len:
                pos_chunk_embeds_2 = torch.nn.functional.pad(pos_chunk_embeds_2, (0, 0, 0, seq_len - pos_chunk_embeds_2.shape[1]), value=0)

            chunk_combined_pos_embeds = torch.cat([pos_chunk_embeds_1, pos_chunk_embeds_2], dim=-1)

            # --- NEW: Store first chunk's pooled embeddings ---
            if i == 0:
                first_chunk_pooled_prompt_embeds = pos_pooled_embeds_2

            # --- NEW: Concatenate embeddings ---
            if final_prompt_embeds is None:  # First chunk
                final_prompt_embeds = chunk_combined_pos_embeds
            else:  # Subsequent chunks
                final_prompt_embeds = torch.cat([final_prompt_embeds, chunk_combined_pos_embeds], dim=1)

            # --- Process Negative Prompt Chunk ---
            # Get the slice of raw tokens for this chunk
            neg_chunk_ids_1_slice = neg_input_ids_1_raw[start_idx:end_idx]
            neg_chunk_ids_2_slice = neg_input_ids_2_raw[start_idx:end_idx]

            # Add special tokens ([BOS]...[EOS]) and pad to max_length (77) for Encoder 1
            neg_chunk_ids_1_padded = [tokenizer.bos_token_id] + neg_chunk_ids_1_slice + [tokenizer.eos_token_id]
            neg_chunk_attention_mask_1 = [1] * len(neg_chunk_ids_1_padded)
            padding_length_1_neg = max_length - len(neg_chunk_ids_1_padded)
            if padding_length_1_neg > 0:
                neg_chunk_ids_1_padded += [pad_token_id_1] * padding_length_1_neg
                neg_chunk_attention_mask_1 += [0] * padding_length_1_neg
            neg_chunk_ids_1_tensor = torch.tensor([neg_chunk_ids_1_padded], device=device)
            neg_chunk_attention_mask_1_tensor = torch.tensor([neg_chunk_attention_mask_1], device=device)

            # Add special tokens ([BOS]...[EOS]) and pad to max_length (77) for Encoder 2
            neg_chunk_ids_2_padded = [tokenizer_2.bos_token_id] + neg_chunk_ids_2_slice + [tokenizer_2.eos_token_id]
            neg_chunk_attention_mask_2 = [1] * len(neg_chunk_ids_2_padded)
            padding_length_2_neg = max_length - len(neg_chunk_ids_2_padded)
            if padding_length_2_neg > 0:
                neg_chunk_ids_2_padded += [pad_token_id_2] * padding_length_2_neg
                neg_chunk_attention_mask_2 += [0] * padding_length_2_neg
            neg_chunk_ids_2_tensor = torch.tensor([neg_chunk_ids_2_padded], device=device)
            neg_chunk_attention_mask_2_tensor = torch.tensor([neg_chunk_attention_mask_2], device=device)


            # Encode negative chunk with Text Encoder 1
            neg_chunk_embeds_1 = text_encoder(
                neg_chunk_ids_1_tensor,
                attention_mask=neg_chunk_attention_mask_1_tensor,
                output_hidden_states=True,
                return_dict=True,
            ).hidden_states[-2]

            # Encode negative chunk with Text Encoder 2
            neg_chunk_output_2 = text_encoder_2(
                neg_chunk_ids_2_tensor,
                attention_mask=neg_chunk_attention_mask_2_tensor,
                output_hidden_states=True,
                return_dict=True,
            )
            neg_chunk_embeds_2 = neg_chunk_output_2.hidden_states[-2]
            
            # Access text_embeds for the pooled output from CLIPTextModelWithProjection
            if hasattr(neg_chunk_output_2, 'text_embeds'):
                # CLIPTextModelWithProjection provides text_embeds
                neg_pooled_embeds_2 = neg_chunk_output_2.text_embeds
            elif hasattr(neg_chunk_output_2, 'pooled_output'):
                # Legacy access for backward compatibility
                neg_pooled_embeds_2 = neg_chunk_output_2.pooled_output
            else:
                # Fallback - use the last hidden state's first token ([CLS]/[BOS]) as pooled representation
                logger.warning("No pooled embeddings found for negative prompt, falling back to first token of last hidden state")
                neg_pooled_embeds_2 = neg_chunk_output_2.last_hidden_state[:, 0]

            # Concatenate negative hidden states
            # Ensure tensors have the same sequence length before concatenating
            seq_len_neg = max(neg_chunk_embeds_1.shape[1], neg_chunk_embeds_2.shape[1])
            if neg_chunk_embeds_1.shape[1] != seq_len_neg:
                neg_chunk_embeds_1 = torch.nn.functional.pad(neg_chunk_embeds_1, (0, 0, 0, seq_len_neg - neg_chunk_embeds_1.shape[1]), value=0)
            if neg_chunk_embeds_2.shape[1] != seq_len_neg:
                neg_chunk_embeds_2 = torch.nn.functional.pad(neg_chunk_embeds_2, (0, 0, 0, seq_len_neg - neg_chunk_embeds_2.shape[1]), value=0)

            chunk_combined_neg_embeds = torch.cat([neg_chunk_embeds_1, neg_chunk_embeds_2], dim=-1)

            # --- NEW: Store first chunk's pooled negative embeddings ---
            if i == 0:
                first_chunk_negative_pooled_prompt_embeds = neg_pooled_embeds_2

            # --- NEW: Concatenate negative embeddings ---
            if final_negative_prompt_embeds is None:  # First chunk
                final_negative_prompt_embeds = chunk_combined_neg_embeds
            else:  # Subsequent chunks
                final_negative_prompt_embeds = torch.cat([final_negative_prompt_embeds, chunk_combined_neg_embeds], dim=1)

        # --- MODIFIED: Use the concatenated embeddings directly ---
        prompt_embeds = final_prompt_embeds
        negative_prompt_embeds = final_negative_prompt_embeds
        
        # --- MODIFIED: Use first chunk's pooled embeddings ---
        pooled_prompt_embeds = first_chunk_pooled_prompt_embeds
        negative_pooled_prompt_embeds = first_chunk_negative_pooled_prompt_embeds
        
        # Handle case where negative prompt might be empty initially
        if negative_prompt == "" and first_chunk_negative_pooled_prompt_embeds is None:
            # Create zero pooled embeds if negative prompt was empty
            if pooled_prompt_embeds is not None and negative_pooled_prompt_embeds is None:
                _, _, _, empty_neg_pooled = pipe.encode_prompt(prompt="", negative_prompt="", device=device, num_images_per_prompt=1)
                negative_pooled_prompt_embeds = empty_neg_pooled.to(dtype=pooled_prompt_embeds.dtype, device=device)

        # Check for NaN or Inf values before returning
        if torch.isnan(prompt_embeds).any() or torch.isinf(prompt_embeds).any():
                logger.warning("NaN or Inf values detected in final positive embeddings. Replacing with zeros.")
                prompt_embeds = torch.nan_to_num(prompt_embeds)

        if torch.isnan(negative_prompt_embeds).any() or torch.isinf(negative_prompt_embeds).any():
                logger.warning("NaN or Inf values detected in final negative embeddings. Replacing with zeros.")
                negative_prompt_embeds = torch.nan_to_num(negative_prompt_embeds)

        if torch.isnan(pooled_prompt_embeds).any() or torch.isinf(pooled_prompt_embeds).any():
                logger.warning("NaN or Inf values detected in final pooled positive embeddings. Replacing with zeros.")
                pooled_prompt_embeds = torch.nan_to_num(pooled_prompt_embeds)

        if torch.isnan(negative_pooled_prompt_embeds).any() or torch.isinf(negative_pooled_prompt_embeds).any():
                logger.warning("NaN or Inf values detected in final pooled negative embeddings. Replacing with zeros.")
                negative_pooled_prompt_embeds = torch.nan_to_num(negative_pooled_prompt_embeds)

    # REMOVED: Batch size expansion happens in the run method instead
    # No longer repeating embeddings for batch_size here
    
    logger.info(f"Completed chunked encoding of prompt with {num_chunks} chunks.")
    logger.debug(f"Final embeds shape: {prompt_embeds.shape}, pooled shape: {pooled_prompt_embeds.shape}")
    logger.debug(f"Negative embeds shape: {negative_prompt_embeds.shape}, negative pooled shape: {negative_pooled_prompt_embeds.shape}")

    return prompt_embeds, negative_prompt_embeds, pooled_prompt_embeds, negative_pooled_prompt_embeds
