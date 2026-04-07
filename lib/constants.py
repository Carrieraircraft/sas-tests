"""SAS 测试框架全局常量"""

# --- ID 范围 ---
SPEC_ID_RANGE = range(0, 128)
MODULE_ID_RANGE = range(0, 128)
SAFE_TEST_RANGE = range(100, 128)  # 测试专用高编号，避免影响生产数据

# --- 性能阈值 (毫秒) ---
MAX_LIST_RESPONSE_MS = 200
MAX_SINGLE_RESPONSE_MS = 100
MAX_CONCURRENT_RESPONSE_MS = 500

# --- 物理限制 ---
MCU_SCREW_SLOTS = 16
MCU_MODULE_SLOTS = 8
MAX_UNIQUE_SPECS_PER_MODULE = 16
MAX_STEPS_PER_SPEC = 8
MAX_POINT_COUNT = 16

# --- 超时 (秒) ---
DEFAULT_WS_TIMEOUT = 5.0
STRESS_WS_TIMEOUT = 30.0
BACKEND_RESTART_TIMEOUT = 30.0

# --- 默认连接 ---
DEFAULT_WS_URL = "ws://192.168.0.221:80"

# --- WS 消息类型 ---
class MsgType:
    # 螺丝规格
    SPEC_OPTIONS_GET = "screw_specification_options_get"
    SPEC_OPTIONS_RESPONSE = "screw_specification_options_get_response"
    SCREW_PARAM_GET = "screw_param_get"
    SCREW_PARAM_GET_RESPONSE = "screw_param_get_response"
    SCREW_STEP_GET = "screw_step_param_get"
    SCREW_STEP_RESPONSE = "screw_step_param_get_response"
    SCREW_PARAM_CONFIG = "screw_param_config"
    # 保存配置应答（与后端 sendScrewParamConfigResponse 一致）
    SCREW_PARAM_SAVE_RESPONSE = "screw_param_response"
    SCREW_PARAM_CONFIG_RESPONSE = "screw_param_response"
    # 引用计数 + COW
    SPEC_REF_QUERY = "screw_spec_reference_query"
    SPEC_REF_RESPONSE = "screw_spec_reference_response"
    SPEC_CLONE = "screw_spec_clone"
    SPEC_CLONE_RESPONSE = "screw_spec_clone_response"
    SPEC_SET_ACTIVE = "screw_spec_set_active"
    SPEC_SET_ACTIVE_RESPONSE = "screw_spec_set_active_response"
    # 统一模组
    MODULE_CONFIG = "module_config"
    MODULE_CONFIG_RESPONSE = "module_config_response"
    MODULE_GET = "module_get"
    MODULE_GET_RESPONSE = "module_get_response"
    MODULE_LIST_GET = "module_list_get"
    MODULE_LIST_RESPONSE = "module_list_get_response"
    MODULE_ERROR = "module_error"
    # 系统
    SYSTEM_PARAM_UPDATE = "system_param_update"
    SYSTEM_PARAM_UPDATE_RESPONSE = "system_param_update_response"
    SYSTEM_PARAMS_BATCH_UPDATE = "system_params_batch_update"
    SYSTEM_PARAMS_BATCH_UPDATE_RESPONSE = "system_params_batch_update_response"
    DATA_RESPONSE = "data_response"
    PING = "ping"
    PONG = "pong"
    # 角色
    ROLE_SWITCH = "role_switch"
    ROLE_SWITCH_RESPONSE = "role_switch_response"
    # 硬件状态推送
    HARDWARE_STATUS_UPDATE = "hardware_status_update"
    # 槽位状态（MCU 物理槽位 ↔ 逻辑 ID 映射）
    SLOT_STATUS_GET = "slot_status_get"
    SLOT_STATUS_RESPONSE = "slot_status_get_response"
