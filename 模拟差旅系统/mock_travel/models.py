"""只检查请求结构；不执行提交业务校验。"""
from typing import List, Literal, Optional
from typing_extensions import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Identifier = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=128)]
DateText = Annotated[str, StringConstraints(strict=True, pattern=r"^\d{4}-\d{2}-\d{2}$")]
Reason = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=4000)]
FailureText = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=1000)]


class Trip(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dateFrom: DateText = Field(description="本段出发日，YYYY-MM-DD")
    dateTo: DateText = Field(description="本段到达日，非目的地停留结束日")
    cityFrom: Identifier = Field(description="出发城市编码")
    cityTo: Identifier = Field(description="到达城市编码")
    tool: Identifier = Field(description="本地采用类别-选项，如火车-二等座")


class ApplicationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    remark: Reason = Field(description="事由")
    dqydbg: Optional[Literal["Y"]] = Field(..., description="普通差旅传 null，短期异地办公传 Y")
    trips: List[Trip] = Field(min_length=1, max_length=40, description="行程对象数组，不添加 items 包装")
    applicantId: Identifier = Field(default="DEMO_EMP_001", description="本地扩展，默认普通演示员工")
    departmentId: Identifier = Field(default="DEMO_DEPT_001", description="本地扩展，默认部门")
    payerCompanyId: Identifier = Field(default="DEMO_COMPANY_001", description="本地扩展，默认付款公司")


class ScenarioUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    submissionResult: Literal["SUCCESS", "FAILURE"] = Field(description="预设提交结果，与申请内容无关")
    failureMessage: Optional[FailureText] = Field(default=None, description="省略则保留已有失败说明")
