# This file is part of Xpra.
# Copyright (C) 2018-2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os.path
from subprocess import check_call

from xpra.os_util import POSIX
from xpra.util.env import osexpand
from xpra.util.parsing import parse_simple_dict

DISCLAIMER = """
IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT,
INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES(INCLUDING,
BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF
LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT(INCLUDING NEGLIGENCE
OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE,
EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
""".replace("\n", "")


def sync() -> None:
    if POSIX:
        check_call("sync")


def get_user_config_file() -> str:
    from xpra.platform.paths import get_user_conf_dirs
    return osexpand(os.path.join(get_user_conf_dirs()[0], "99_configure_tool.conf"))


def parse_user_config_file() -> dict:
    filename = get_user_config_file()
    if not os.path.exists(filename):
        return {}
    with open(filename, "r", encoding="utf8") as f:
        data = f.read().replace("\r", "\n")
        return parse_simple_dict(data, sep="\n")


def save_user_config_file(options: dict) -> None:
    filename = get_user_config_file()
    with open(filename, "w", encoding="utf8") as f:
        for k, v in options.items():
            f.write(f"{k} = {v}\n")
