

import time
import torch
import numpy as np
import onnxruntime
from transformers import AutoModelForCausalLM, AutoTokenizer
import shutil

path = 'C:/Users/Downloads/MiniCPM-2B-dpo-fp32'  # Set the folder path where the MiniCPM whole project downloaded.

# Replace the original "modeling_minicpm.py" with the modified "modeling_minicpm.py", which stored at the folder "modeling_modified_A&B".
modified_path_A = './modeling_modified_A/modeling_minicpm.py'  # The path where the modified part_A modeling_minicpm.py stored.
modified_path_B = './modeling_modified_B/modeling_minicpm.py'  # The path where the modified part_B modeling_minicpm.py stored.
onnx_model_A = 'C:/Users/Downloads/MiniCPM_ONNX_A/MiniCPM_part_A.onnx'  # Assign a path where the exported MiniCPM_part_A stored.
onnx_model_B = 'C:/Users/Downloads/MiniCPM_ONNX_B/MiniCPM_part_B.onnx'  # Assign a path where the exported MiniCPM_part_B stored.

# Load the model
shutil.copyfile(modified_path_A, path + "/modeling_minicpm.py")
model = AutoModelForCausalLM.from_pretrained(path, torch_dtype=torch.float32, device_map='cpu', trust_remote_code=True).float().eval()
max_seq_len = 1024  # Please modify the same variable, which declared in the modified modeling_minicpm.py on line 1009, at the same time.
num_heads = model.config.num_attention_heads
head_dim = model.config.hidden_size // num_heads
num_key_value_heads = model.config.num_key_value_heads
num_layers = model.config.num_hidden_layers // 2  # The original value was 40, but we divided it in half to ensure the size of a single file is less than 2GB after the int8 quantized.
hidden_size = model.config.hidden_size

# Generate dummies for torch.onnx.export()
input_ids = torch.ones(max_seq_len, dtype=torch.int32)
attention_mask = torch.zeros(1, dtype=torch.float32) - 999999999.0
ids_len = torch.zeros(1, dtype=torch.long) + 10  # "10" is just a dummy value.
history_len = torch.zeros(1, dtype=torch.long) + 10  # "10" is just a dummy value.
past_key_states = torch.zeros((num_layers, num_key_value_heads, max_seq_len, head_dim), dtype=torch.float16)
past_values_states = past_key_states
last_hidden_state = torch.ones((max_seq_len, hidden_size), dtype=torch.float32)
position_ids = torch.zeros((max_seq_len, 1), dtype=torch.float32)
for i in range(max_seq_len):
    position_ids[i, 0] = float(i)
theta = 10000.0 ** -(torch.arange(0, head_dim, 2, dtype=torch.float32) / head_dim)
idx_theta = position_ids * theta
cos_rotary_pos_emb = torch.cos(idx_theta)
sin_rotary_pos_emb = torch.sin(idx_theta)
cos_rotary_pos_emb = torch.cat((cos_rotary_pos_emb, cos_rotary_pos_emb), dim=-1).unsqueeze(0).half()
sin_rotary_pos_emb = torch.cat((sin_rotary_pos_emb, sin_rotary_pos_emb), dim=-1).unsqueeze(0).half()
model.register_buffer('cos_rotary_pos_emb', cos_rotary_pos_emb)
model.register_buffer('sin_rotary_pos_emb', sin_rotary_pos_emb)

print('Part_A export start ...')
torch.onnx.export(
    model, (
        input_ids, attention_mask, past_key_states, past_values_states, history_len, ids_len),
    onnx_model_A,
    input_names=[
        'input_ids',
        'attention_mask',
        'past_key_states',
        'past_values_states',
        'history_len',
        'ids_len'
    ],
    output_names=['last_hidden_state', 'past_key_states', 'past_values_states'],
    do_constant_folding=True,
    opset_version=17)
del model
print('Part_A export done!')

# Reload for part B
shutil.copyfile(modified_path_B, path + "/modeling_minicpm.py")
model = AutoModelForCausalLM.from_pretrained(path, torch_dtype=torch.float32, device_map='cpu', trust_remote_code=True).float().eval()
print('Part_B export start ...')
torch.onnx.export(
    model, (
        last_hidden_state, attention_mask, past_key_states, past_values_states, history_len, ids_len),
    onnx_model_B,
    input_names=[
        'last_hidden_state',
        'attention_mask',
        'past_key_states',
        'past_values_states',
        'history_len',
        'ids_len'
    ],
    output_names=['max_logit_id', 'past_key_states', 'past_values_states'],
    do_constant_folding=True,
    opset_version=17)
del model
del past_key_states
del past_values_states
del position_ids
del theta
del idx_theta
del cos_rotary_pos_emb
del sin_rotary_pos_emb
print('Part_B export done!')

print('\nStart running the MiniCPM by ONNX Runtime.')
print('Now loading . . . it could cost minutes.\n')

# Run the exported model by ONNX Runtime
query = "山东省最高的山是哪座山, 它比黄山高还是矮？差距多少？"
max_single_chat_length = 341  # It a adjustable value, but must less than max_seq_len.
tokenizer = AutoTokenizer.from_pretrained(path, trust_remote_code=True)

# ONNX Runtime settings
session_opts = onnxruntime.SessionOptions()
session_opts.log_severity_level = 3  # error level, it a adjustable value.
session_opts.inter_op_num_threads = 0  # Run different nodes with num_threads. Set 0 for auto.
session_opts.intra_op_num_threads = 4  # Under the node, execute the operators with num_threads. Set 0 for auto.
session_opts.enable_cpu_mem_arena = True  # True for execute speed; False for less memory usage.
session_opts.execution_mode = onnxruntime.ExecutionMode.ORT_SEQUENTIAL
session_opts.graph_optimization_level = onnxruntime.GraphOptimizationLevel.ORT_ENABLE_ALL

ort_session_A = onnxruntime.InferenceSession(onnx_model_A, sess_options=session_opts, providers=['CPUExecutionProvider'])
in_name_A = ort_session_A.get_inputs()
out_name_A = ort_session_A.get_outputs()
in_name_A0 = in_name_A[0].name
in_name_A1 = in_name_A[1].name
in_name_A2 = in_name_A[2].name
in_name_A3 = in_name_A[3].name
in_name_A4 = in_name_A[4].name
in_name_A5 = in_name_A[5].name
out_name_A0 = out_name_A[0].name
out_name_A1 = out_name_A[1].name
out_name_A2 = out_name_A[2].name

ort_session_B = onnxruntime.InferenceSession(onnx_model_B, sess_options=session_opts, providers=['CPUExecutionProvider'])
in_name_B = ort_session_B.get_inputs()
out_name_B = ort_session_B.get_outputs()
in_name_B0 = in_name_B[0].name
in_name_B1 = in_name_B[1].name
in_name_B2 = in_name_B[2].name
in_name_B3 = in_name_B[3].name
in_name_B4 = in_name_B[4].name
in_name_B5 = in_name_B[5].name
out_name_B0 = out_name_B[0].name
out_name_B1 = out_name_B[1].name
out_name_B2 = out_name_B[2].name

# Pre-process inputs
prompt = tokenizer.apply_chat_template([{"role": 'user', "content": query}], tokenize=False, add_generation_prompt=False)
token = tokenizer(prompt, return_tensors='pt')['input_ids']
ids_len = token.shape[1] + np.zeros(1, dtype=np.int64)
input_ids = np.zeros(max_seq_len, dtype=np.int32)
input_ids[:ids_len[0]] = token[0, :]
attention_mask = np.zeros(1, dtype=np.float32) - 999999999.0
history_len = np.zeros(1, dtype=np.int64)
past_key_states_A = np.zeros((num_layers, num_key_value_heads, max_seq_len, head_dim), dtype=np.float16)
past_values_states_A = past_key_states_A
past_key_states_B = past_key_states_A
past_values_states_B = past_key_states_A
num_decode = 0
print('Test Question: ' + query + "\n")
print('MiniCPM Answering:\n')

# Start to run LLM
start_time = time.time()
while history_len < max_single_chat_length:
    last_hidden_state, past_key_states_A, past_values_states_A = ort_session_A.run(
        [out_name_A0, out_name_A1, out_name_A2],
        {in_name_A0: input_ids,
         in_name_A1: attention_mask,
         in_name_A2: past_key_states_A,
         in_name_A3: past_values_states_A,
         in_name_A4: history_len,
         in_name_A5: ids_len})
    token_id, past_key_states_B, past_values_states_B = ort_session_B.run([out_name_B0, out_name_B1, out_name_B2],
                                                                          {in_name_B0: last_hidden_state,
                                                                           in_name_B1: attention_mask,
                                                                           in_name_B2: past_key_states_B,
                                                                           in_name_B3: past_values_states_B,
                                                                           in_name_B4: history_len,
                                                                           in_name_B5: ids_len})
    if token_id == 2:  # the stop_id in MiniCPM is "2"
        break
    else:
        history_len[0] += ids_len[0]
        ids_len[0] = 1
        num_decode += 1
        attention_mask[0] = 0.0
        input_ids[0] = token_id
        print(tokenizer.convert_tokens_to_string([tokenizer._convert_id_to_token(token_id)]), end="", flush=True)
end_time = time.time()
print("\n")
print(num_decode / (end_time - start_time))
print("token/s")
