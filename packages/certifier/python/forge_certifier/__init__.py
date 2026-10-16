"""forge_certifier：C1 本机认证器（M09 §3.2；凭证不出本机 G11）。"""

__version__ = "0.1.0"

from .certify import accept_spotcheck  # noqa: E402  （版本号先行，避免循环导入）

__all__ = ["accept_spotcheck", "__version__"]
