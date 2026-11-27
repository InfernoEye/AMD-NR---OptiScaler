"""Read-only Steam launch options and conservative merge tests."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1] / "steam_user_launch.py"
spec = importlib.util.spec_from_file_location("steam_user_launch", SOURCE)
launch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launch)


def localconfig(options: str, appid: str = "1422450") -> str:
    escaped = options.replace("\\", "\\\\").replace('"', '\\"')
    return ('"UserLocalConfigStore" { "Software" { "Valve" { "Steam" { '
            '"apps" { "999" { "LaunchOptions" "wrong game" } '
            '"' + appid + '" { "LaunchOptions" "' + escaped +
            '" } } } } } }')


class SteamUserLaunchTests(unittest.TestCase):
    def test_exact_appid_and_nested_keyvalues(self):
        value = "PROTON_ENABLE_NVAPI=1 gamemoderun %command% -novid"
        self.assertEqual(launch._launch_option_from_vdf(localconfig(value), "1422450"),
                         value)
        self.assertIsNone(launch._launch_option_from_vdf(localconfig(value), "7"))

    def test_escaped_quotes(self):
        original = 'WINEDLLOVERRIDES="version=n,b" mangohud %command%'
        self.assertEqual(launch._launch_option_from_vdf(localconfig(original), "1422450"),
                         original)

    def test_merge_existing_variable_and_wrapper(self):
        original = 'PROTON_ENABLE_NVAPI=1 WINEDLLOVERRIDES="version=n,b" mangohud %command% -novid'
        outcome = launch.preview_launch_options(original, "dxgi.dll")
        self.assertEqual(outcome["status"], "merged")
        self.assertEqual(outcome["preview"],
                         'PROTON_ENABLE_NVAPI=1 WINEDLLOVERRIDES="version=n,b;dxgi=n,b" mangohud %command% -novid')

    def test_update_existing_selected_override_only_once(self):
        options = 'WINEDLLOVERRIDES="dxgi=b;version=n,b" %command%'
        final = launch.preview_launch_options(options, "dxgi.dll")
        self.assertEqual(final["preview"],
                         'WINEDLLOVERRIDES="version=n,b;dxgi=n,b" %command%')

    def test_grouped_dll_override_is_retained(self):
        options = 'WINEDLLOVERRIDES="dxgi,version=n,b;winmm=b" %command%'
        final = launch.preview_launch_options(options, "dxgi.dll")
        self.assertEqual(final["preview"],
                         'WINEDLLOVERRIDES="version=n,b;winmm=b;dxgi=n,b" %command%')

    def test_no_override_with_existing_env_and_arguments(self):
        result = launch.preview_launch_options('MANGOHUD=1 %command% -vulkan', 'dxgi.dll')
        self.assertEqual(result["preview"],
                         'WINEDLLOVERRIDES="dxgi=n,b" MANGOHUD=1 %command% -vulkan')

    def test_plain_arguments_gain_placeholder(self):
        result = launch.preview_launch_options('-novid -vulkan', 'dxgi.dll')
        self.assertEqual(result["preview"],
                         'WINEDLLOVERRIDES="dxgi=n,b" %command% -novid -vulkan')

    def test_unsafe_or_unsupported_options_are_not_composed(self):
        for original in ('WINEDLLOVERRIDES="$MY_DLLS" %command%',
                         'WINEDLLOVERRIDES="dxgi=n,b" WINEDLLOVERRIDES="version=n,b" %command%',
                         'WINEDLLOVERRIDES="invalid" %command%'):
            with self.subTest(original=original):
                self.assertIsNone(launch.preview_launch_options(original, "dxgi.dll")["preview"])
        self.assertIsNone(launch.preview_launch_options("", "OptiScaler.asi")["preview"])

    def test_profile_disagreement_and_same_values(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for profile, value in [("111", "gamemoderun %command%"),
                                   ("222", "mangohud %command%")]:
                target = root / "userdata" / profile / "config/localconfig.vdf"
                target.parent.mkdir(parents=True)
                target.write_text(localconfig(value), encoding="utf-8")
            ambiguous = launch.read_launch_options(1422450, [root])
            self.assertEqual(ambiguous["status"], "multiple_profiles")
            self.assertIsNone(ambiguous["existing"])
            (root / "userdata/222/config/localconfig.vdf").write_text(
                localconfig("gamemoderun %command%"), encoding="utf-8")
            matching = launch.read_launch_options(1422450, [root])
            self.assertEqual(matching["status"], "found")
            self.assertEqual(matching["existing"], "gamemoderun %command%")

    def test_missing_options_and_missing_profiles(self):
        with tempfile.TemporaryDirectory() as temp:
            self.assertEqual(launch.read_launch_options(1422450, [Path(temp)])["status"],
                             "empty")
            config = Path(temp) / "userdata/111/config/localconfig.vdf"
            config.parent.mkdir(parents=True)
            config.write_text(localconfig("other", "444"), encoding="utf-8")
            self.assertEqual(launch.read_launch_options(1422450, [Path(temp)])["status"],
                             "empty")


if __name__ == "__main__":
    unittest.main()
