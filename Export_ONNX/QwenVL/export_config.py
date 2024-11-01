INPUT_IMAGE_SIZE = [720, 1280]                          # Input image shape. Should be a multiple of GPU group (e.g., 16) for optimal efficiency.
HEIGHT_FACTOR = 20                                      # Adjust this value to determine the resize shape.
WIDTH_FACTOR = 36                                       # Adjust this value to determine the resize shape.
IMAGE_RESIZE = [HEIGHT_FACTOR * 28, WIDTH_FACTOR * 28]  # 28 = self.patch_size * self.merge_size
MAX_SEQ_LENGTH = 1024                                   # The max token length. Note, this value include the 10 tokens for system prompt and 720 tokens for image prompt. Hence, only (MAX_SEQ_LENGTH - 730) tokens for query + response.

