import time
import torch
import numpy as np
import onnxruntime
from PIL import Image
import shutil
import gc
import os
try:
    from export_config import INPUT_IMAGE_SIZE, IMAGE_RESIZE, MAX_SEQ_LENGTH, HEIGHT_FACTOR, WIDTH_FACTOR
except:
    # Default Values if import failed
    INPUT_IMAGE_SIZE = [960, 960]                                       # Input image shape. Should be a multiple of GPU group (e.g., 16) for optimal efficiency.
    HEIGHT_FACTOR = 10                                                  # Adjust this value to determine the resize shape and vision resolution.
    WIDTH_FACTOR = 10                                                   # Adjust this value to determine the resize shape and vision resolution.
    IMAGE_RESIZE = [HEIGHT_FACTOR * 28, WIDTH_FACTOR * 28]              # 28 = self.patch_size * self.merge_size
    MAX_SEQ_LENGTH = 1024                                               # The max token length. Note, this value include the 10 tokens for system prompt and (HEIGHT_FACTOR * WIDTH_FACTOR) tokens for image prompt. Hence, only (MAX_SEQ_LENGTH - (HEIGHT_FACTOR * WIDTH_FACTOR) - 10) tokens for query + response.

path = r'/home/dake/Downloads/Qwen2-VL-2B-Instruct/'                    # Set the folder path where the Qwen2-VL whole project downloaded.
# Replace the original "modeling_qwen2_vl.py" with the modified "modeling_qwen2_vl.py", which stored at the folder "modeling_modified".
modified_path_E = r'./modeling_modified/part_E/modeling_qwen2_vl.py'    # The path where the modified modeling_qwen2_vl.py stored.
onnx_model_A = r'/home/dake/Downloads/Qwen/QwenVL_A.onnx'               # Assign a path where the exported QwenVL model stored.
onnx_model_B = r'/home/dake/Downloads/Qwen/QwenVL_B.onnx'
onnx_model_C = r'/home/dake/Downloads/Qwen/QwenVL_C.onnx'
onnx_model_D = r'/home/dake/Downloads/Qwen/QwenVL_D.onnx'
onnx_model_E = r'/home/dake/Downloads/Qwen/QwenVL_E.onnx'
transformers_qwen2_path = r'/home/dake/anaconda3/envs/python_311b/lib/python3.11/site-packages/transformers/models/qwen2_vl/modeling_qwen2_vl.py'  # The original modeling_qwen2_vl.py path which was stored in the transformers python package.

image_path = r"./psyduck.png"                                           # Test image for the exported onnx model.
query = "Describe this image."                                          # Test query for the exported onnx model.

shutil.copyfile(modified_path_E, transformers_qwen2_path)
shutil.copyfile("export_config.py", transformers_qwen2_path.replace("modeling_qwen2_vl", "export_config"))

from transformers import Qwen2VLForConditionalGeneration, AutoTokenizer


def is_valid_image_path(image_path):
    if not os.path.exists(image_path):
        return False
    valid_extensions = {'.jpg', '.jpeg', '.png', '.bmp', '.gif', '.tiff'}
    _, ext = os.path.splitext(image_path)
    return ext.lower() in valid_extensions


# Load the model
with torch.inference_mode():
    model = Qwen2VLForConditionalGeneration.from_pretrained(path, torch_dtype=torch.float32, device_map="cpu", low_cpu_mem_usage=True)
    max_seq_len = MAX_SEQ_LENGTH  # Please modify the same variable, which declared in the modified modeling_qwen2.py on line 1001, at the same time.
    num_heads = model.config.num_attention_heads
    num_key_value_heads = model.config.num_key_value_heads
    head_dim = model.config.hidden_size // num_heads
    num_layers = model.config.num_hidden_layers
    hidden_size = model.config.hidden_size

    past_key_states = torch.zeros((num_layers, num_key_value_heads, max_seq_len, head_dim), dtype=torch.float16)
    past_value_states = past_key_states
    history_len = torch.tensor([10], dtype=torch.long)  # "10" is just a dummy value.
    ids_len = torch.tensor([10], dtype=torch.long)  # "10" is just a dummy value.
    image_embed_size = WIDTH_FACTOR * HEIGHT_FACTOR
    image_pad_len = torch.tensor([image_embed_size], dtype=torch.long)
    ids_len = ids_len + image_pad_len
    hidden_states = torch.ones((ids_len, hidden_size), dtype=torch.float32)
    position_ids = torch.ones((3, 1, ids_len), dtype=torch.float32)
    kv_seq_len = ids_len + history_len
    attention_mask = torch.ones((1, ids_len, kv_seq_len), dtype=torch.float32)

    sqrt_hidden_size = torch.sqrt(torch.tensor(hidden_size, dtype=torch.float32))
    model.model.norm.weight.data *= sqrt_hidden_size
    for i in range(num_layers):
        model.model.layers._modules[f'{i}'].input_layernorm.weight.data *= sqrt_hidden_size
        model.model.layers._modules[f'{i}'].post_attention_layernorm.weight.data *= sqrt_hidden_size

        layer_attn = model.model.layers._modules[f'{i}'].self_attn
        qkv_weight = torch.cat([layer_attn.q_proj.weight.data, layer_attn.k_proj.weight.data, layer_attn.v_proj.weight.data], dim=0)
        qkv_bias = torch.cat([layer_attn.q_proj.bias.data, layer_attn.k_proj.bias.data, layer_attn.v_proj.bias.data], dim=0)
        layer_attn.qkv_proj = torch.nn.Linear(qkv_weight.shape[1], qkv_weight.shape[0], bias=True)
        layer_attn.qkv_proj.weight.data.copy_(qkv_weight)
        layer_attn.qkv_proj.bias.data.copy_(qkv_bias)
        del layer_attn.q_proj
        del layer_attn.k_proj
        del layer_attn.v_proj
        gc.collect()

    print('\nExport Part_E Start...')
    torch.onnx.export(
        model,
        (hidden_states, attention_mask, past_key_states, past_value_states, history_len, kv_seq_len, position_ids),
        onnx_model_E,
        input_names=[
            'hidden_states',
            'attention_mask',
            'past_key_states',
            'past_value_states',
            'history_len',
            'kv_seq_len',
            'position_ids'
        ],
        output_names=['max_logit_ids', 'past_key_states', 'past_value_states'],
        dynamic_axes={
            'hidden_states': {0: 'ids_len'},
            'attention_mask': {1: 'ids_len', 2: 'kv_seq_len'},
            'position_ids': {2: 'ids_len'}
        },
        do_constant_folding=True,
        opset_version=17
    )
    del model
    del hidden_states
    del attention_mask
    del past_key_states
    del past_value_states
    del history_len
    del ids_len
    del kv_seq_len
    del position_ids
    gc.collect()
    print('\nExport Part_E Done!')

print('\nStart running the QwenVL by ONNXRuntime.')
print('\nNow loading . . . it could cost minutes.')

# Run the exported model by ONNX Runtime
max_single_chat_length = 341  # It a adjustable value, but must less than max_seq_len.
tokenizer = AutoTokenizer.from_pretrained(path, trust_remote_code=True)

# ONNX Runtime settings
session_opts = onnxruntime.SessionOptions()
session_opts.log_severity_level = 3  # error level, it a adjustable value.
session_opts.inter_op_num_threads = 0  # Run different nodes with num_threads. Set 0 for auto.
session_opts.intra_op_num_threads = 0  # Under the node, execute the operators with num_threads. Set 0 for auto.
session_opts.enable_cpu_mem_arena = True  # True for execute speed; False for less memory usage.
session_opts.execution_mode = onnxruntime.ExecutionMode.ORT_SEQUENTIAL
session_opts.graph_optimization_level = onnxruntime.GraphOptimizationLevel.ORT_ENABLE_ALL
session_opts.add_session_config_entry("session.intra_op.allow_spinning", "1")
session_opts.add_session_config_entry("session.inter_op.allow_spinning", "1")

ort_session_A = onnxruntime.InferenceSession(onnx_model_A, sess_options=session_opts, providers=['CPUExecutionProvider'])
in_name_A = ort_session_A.get_inputs()
out_name_A = ort_session_A.get_outputs()
in_name_A0 = in_name_A[0].name
out_name_A0 = out_name_A[0].name

ort_session_B = onnxruntime.InferenceSession(onnx_model_B, sess_options=session_opts, providers=['CPUExecutionProvider'])
in_name_B = ort_session_B.get_inputs()
out_name_B = ort_session_B.get_outputs()
in_name_B0 = in_name_B[0].name
in_name_B1 = in_name_B[1].name
out_name_B0 = out_name_B[0].name
out_name_B1 = out_name_B[1].name

ort_session_C = onnxruntime.InferenceSession(onnx_model_C, sess_options=session_opts, providers=['CPUExecutionProvider'])
in_name_C = ort_session_C.get_inputs()
out_name_C = ort_session_C.get_outputs()
in_name_C0 = in_name_C[0].name
in_name_C1 = in_name_C[1].name
out_name_C0 = out_name_C[0].name
out_name_C1 = out_name_C[1].name
out_name_C2 = out_name_C[2].name

ort_session_D = onnxruntime.InferenceSession(onnx_model_D, sess_options=session_opts, providers=['CPUExecutionProvider'])
in_name_D = ort_session_D.get_inputs()
out_name_D = ort_session_D.get_outputs()
in_name_D0 = in_name_D[0].name
in_name_D1 = in_name_D[1].name
in_name_D2 = in_name_D[2].name
out_name_D0 = out_name_D[0].name
out_name_D1 = out_name_D[1].name
out_name_D2 = out_name_D[2].name

ort_session_E = onnxruntime.InferenceSession(onnx_model_E, sess_options=session_opts, providers=['CPUExecutionProvider'])
in_name_E = ort_session_E.get_inputs()
out_name_E = ort_session_E.get_outputs()
in_name_E0 = in_name_E[0].name
in_name_E1 = in_name_E[1].name
in_name_E2 = in_name_E[2].name
in_name_E3 = in_name_E[3].name
in_name_E4 = in_name_E[4].name
in_name_E5 = in_name_E[5].name
in_name_E6 = in_name_E[6].name
out_name_E0 = out_name_E[0].name
out_name_E1 = out_name_E[1].name
out_name_E2 = out_name_E[2].name

# Pre-process inputs
if is_valid_image_path(image_path):
    image = Image.open(image_path)
    image = image.resize((INPUT_IMAGE_SIZE[1], INPUT_IMAGE_SIZE[0]))
    if image.mode != 'RGB':
        image = image.convert('RGB')
    pixel_values = np.transpose(np.array(image).astype(np.float32), (2, 0, 1))
    pixel_values = np.expand_dims(pixel_values, axis=0) / 255.0
    use_vision = True
else:
    use_vision = False

prompt = f"\n<|im_start|>user\n<|vision_start|><|vision_end|>{query}<|im_end|>\n<|im_start|>assistant\n"
token = tokenizer(prompt, return_tensors='pt')['input_ids']
ids_len = token.shape[1] + np.zeros(1, dtype=np.int64)
input_ids = np.zeros(ids_len, dtype=np.int32)
input_ids[:] = token[0, :]
history_len = np.zeros(1, dtype=np.int64)
past_key_states = np.zeros((num_layers, num_key_value_heads, max_seq_len, head_dim), dtype=np.float16)
past_values_states = past_key_states
if use_vision:
    ids_len = np.array([ids_len[0] + image_pad_len[0]], dtype=np.int64)
kv_seq_len = np.array([ids_len[0] + history_len[0]], dtype=np.int64)
num_decode = 0

# Start to run LLM
print('\nStart to Process the Image...')
start_time = time.time()
if use_vision:
    image_embed = ort_session_A.run(
        [out_name_A0],
        {in_name_A0: pixel_values})[0]

hidden_states, _ = ort_session_B.run(
    [out_name_B0, out_name_B1],
    {
        in_name_B0: input_ids,
        in_name_B1: kv_seq_len
    })

position_ids, position_ids_2, attention_mask = ort_session_C.run(
    [out_name_C0, out_name_C1, out_name_C2],
    {
        in_name_C0: ids_len,
        in_name_C1: kv_seq_len
    })

if use_vision:
    hidden_states, position_ids, position_ids_2 = ort_session_D.run(
        [out_name_D0, out_name_D1, out_name_D2],
        {
            in_name_D0: hidden_states,
            in_name_D1: image_embed,
            in_name_D2: ids_len
        })
end_time = time.time()
print(f'\nImage Process Complete. Time Cost: {(end_time - start_time)}')
print('\nTest Question: ' + query + "\n\nQwenVL Answering:\n")

while (num_decode < max_single_chat_length) & (history_len < max_seq_len):
    token_id, past_key_states, past_values_states = ort_session_E.run(
        [out_name_E0, out_name_E1, out_name_E2],
        {
            in_name_E0: hidden_states,
            in_name_E1: attention_mask,
            in_name_E2: past_key_states,
            in_name_E3: past_values_states,
            in_name_E4: history_len,
            in_name_E5: kv_seq_len,
            in_name_E6: position_ids,
        })
    if (token_id == 151643) | (token_id == 151645):  # the stop_id in Qwen is "151643" & "151645"
        break
    else:
        num_decode += 1
        if num_decode < 2:
            position_ids = position_ids_2
            history_len += ids_len[0]
            ids_len[0] = 1
            kv_seq_len[0] = history_len[0] + 1
        else:
            history_len += 1
            position_ids += 1
            kv_seq_len += 1
        hidden_states, attention_mask = ort_session_B.run(
            [out_name_B0, out_name_B1],
            {
                in_name_B0: np.array([token_id], dtype=np.int32),
                in_name_B1: kv_seq_len
            })
        print(tokenizer.decode(token_id), end="", flush=True)

print(f"\n\nText Generate Speed: {num_decode / (time.time() - end_time):.3f} token/s")
