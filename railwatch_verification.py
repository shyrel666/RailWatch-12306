"""Detect when 12306 requires human verification."""

from __future__ import annotations

from typing import Any, Callable, Optional

VERIFICATION_DETECT_JS = r"""
try {
    function visible(el) { return !!(el && el.offsetParent !== null); }
    if (visible(document.querySelector('#nc_1_n1z, .nc_scale, .nc-container, .slide-verify, .geetest_slider_button'))) return true;
    if (visible(document.querySelector('#J-loginImg, #randCode, img[src*="captcha"]'))) return true;
    var dialogs = document.querySelectorAll('.dhtmlx_window_active, .modal, .layui-layer, [class*="dialog"]');
    for (var i = 0; i < dialogs.length; i++) {
        var d = dialogs[i];
        if (!visible(d)) continue;
        var dt = d.innerText || '';
        if (dt.indexOf('人脸') !== -1 && dt.indexOf('核验') !== -1) return true;
        if ((dt.indexOf('滑') !== -1 || dt.indexOf('拖动') !== -1) && dt.indexOf('验证') !== -1) return true;
    }
    var t = (document.body && document.body.innerText) ? document.body.innerText : '';
    if (t.indexOf('请完成安全验证') !== -1 || t.indexOf('拖动下方滑块') !== -1
        || t.indexOf('向右滑动') !== -1 || t.indexOf('请按住滑块') !== -1) return true;
    var href = location.href || '';
    if (href.indexOf('login.html') !== -1 || href.indexOf('/otn/login/init') !== -1) return true;
    return false;
} catch (e) { return false; }
"""

# Legacy callers must not infer a transaction from generic success text or URL.
ALTERNATE_SUCCESS_DETECT_JS = "return false;"



class VerificationDetector:
  def __init__(self, driver, log_callback: Optional[Callable[[str], None]] = None):
    self.driver = driver
    self.log = log_callback or (lambda _message: None)

  def verification_present(self) -> bool:
    try:
      return bool(self.driver.execute_script(VERIFICATION_DETECT_JS))
    except Exception:
      return False

  def alternate_success_present(self) -> bool:
    return False  # Use OrderPage.result with an OrderIntent and order identity.
