from pydantic import BaseModel, ConfigDict


class StrictIn(BaseModel):
    """Base cho mọi schema input mới (ADR-004 S8, S15).

    ``extra="forbid"``: gửi kèm trường lạ (``price``, ``amount``, ``code``, ``created_by``…) -> 422.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
