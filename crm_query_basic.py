"""最小 CRM 查询脚手代码。

只保留 3 个核心业务输入：
1. data_object_api_name: 对象 API 名称
2. limit: 获取条数
3. filters: 筛选条件列表

鉴权部分只保留接口实际会用到的参数。
token 和 EncodingAESKey 不用于这个查询接口，因此这里不使用。
"""

from network import FXiaokeCRM


def query_crm_basic(app_id, app_secret, permanent_code,
                    data_object_api_name, limit=10, filters=None,
                    current_open_user_id=None, admin_mobile=None):
    """根据对象、条数、筛选条件获取 CRM 数据。"""
    crm = FXiaokeCRM(
        app_id=app_id,
        app_secret=app_secret,
        permanent_code=permanent_code,
        admin_mobile=admin_mobile or "",
    )

    if current_open_user_id:
        ok, err = crm.get_corp_access_token()
        if not ok:
            raise RuntimeError(f"获取 corpAccessToken 失败: {err}")
        crm.current_open_user_id = current_open_user_id

    data, err = crm.query_data_object(
        data_object_api_name=data_object_api_name,
        offset=0,
        limit=limit,
        filters=filters or [],
    )
    if err:
        raise RuntimeError(f"CRM 查询失败: {err}")

    return {
        "total": data.get("total", 0),
        "dataList": data.get("dataList", []),
    }


if __name__ == "__main__":
    APP_ID = "FSAID_1323c1a"
    APP_SECRET = "e7f4188d14704299b375c91ddda92cb0"
    PERMANENT_CODE = "E8B8D8536B0385D035657AC2528928F0"

    CURRENT_OPEN_USER_ID = "请填写 currentOpenUserId"
    ADMIN_MOBILE = "15889740213"

    DATA_OBJECT_API_NAME = "CasesObj"
    LIMIT = 10
    FILTERS = [
        {
            "field_name": "device_product_id",
            "operator": "LIKE",
            "field_values": [13.012],
        }
    ]

    result = query_crm_basic(
        app_id=APP_ID,
        app_secret=APP_SECRET,
        permanent_code=PERMANENT_CODE,
        data_object_api_name=DATA_OBJECT_API_NAME,
        limit=LIMIT,
        filters=FILTERS,
        current_open_user_id=None if CURRENT_OPEN_USER_ID == "请填写 currentOpenUserId" else CURRENT_OPEN_USER_ID,
        admin_mobile=None if ADMIN_MOBILE == "请填写管理员手机号" else ADMIN_MOBILE,
    )

    print("total:", result["total"])
    print("count:", len(result["dataList"]))
    for row in result["dataList"]:
        print(row)