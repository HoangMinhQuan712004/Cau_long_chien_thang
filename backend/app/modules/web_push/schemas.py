from pydantic import BaseModel, Field


class PushConfig(BaseModel):
    enabled: bool = Field(description="false khi server chưa cấu hình VAPID -> FE ẩn nút bật")
    public_key: str | None = Field(
        description="applicationServerKey (base64url) cho PushManager.subscribe; null khi tắt"
    )


class SubscriptionKeys(BaseModel):
    p256dh: str = Field(min_length=1, max_length=200)
    auth: str = Field(min_length=1, max_length=100)


class SubscriptionIn(BaseModel):
    """``PushSubscription.toJSON()`` của trình duyệt (bỏ ``expirationTime``) + nhãn máy tùy chọn."""

    endpoint: str = Field(min_length=1, max_length=1000)
    keys: SubscriptionKeys
    device_label: str | None = Field(default=None, max_length=100)


class SubscriptionOut(BaseModel):
    id: int


class UnsubscribeIn(BaseModel):
    endpoint: str = Field(min_length=1, max_length=1000)


class TestPushOut(BaseModel):
    devices: int = Field(description="Số thiết bị của tài khoản sẽ nhận thông báo thử")
