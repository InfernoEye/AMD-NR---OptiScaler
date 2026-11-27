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

    def test_bridge_preview_preserves_wrappers_and_game_arguments(self):
        existing = 'MANGOHUD=1 gamemoderun %command% -novid'
        outcome = launch.preview_bridge_launch(existing, '/mnt/Games/My Game/amdnr-linux/run.sh')
        self.assertEqual(outcome["compose_status"], "ready")
        self.assertEqual(outcome["preview"],
                         'MANGOHUD=1 gamemoderun "/mnt/Games/My Game/amdnr-linux/run.sh" %command% -novid')
        self.assertEqual(outcome["removed"], [])

    def test_bridge_removes_only_recorded_old_proxy_overrides(self):
        existing = ('PROTON_ENABLE_NVAPI=1 WINEDLLOVERRIDES="dxgi,version=n,b;msvcp140=n,b" '
                    'mangohud %command% -launch')
        outcome = launch.preview_bridge_launch(
            existing, '/game/Binaries/Win64/amdnr-linux/run.sh', ('dxgi.dll',))
        self.assertEqual(outcome["compose_status"], "review")
        self.assertIn("Bridge-controlled DXGI override: dxgi=n,b", outcome["removed"])
        self.assertIn('WINEDLLOVERRIDES="version=n,b;msvcp140=n,b"', outcome["preview"])
        self.assertIn('PROTON_ENABLE_NVAPI=1', outcome["preview"])
        self.assertIn('mangohud "/game/Binaries/Win64/amdnr-linux/run.sh" %command% -launch', outcome["preview"])
        self.assertTrue(outcome["review"])

    def test_bridge_drops_empty_old_override_variable(self):
        result = launch.preview_bridge_launch(
            'WINEDLLOVERRIDES="dxgi=n,b" %command% -novid',
            '/game/amdnr-linux/run.sh', ('dxgi.dll',))
        self.assertEqual(result["compose_status"], "ready")
        self.assertEqual(result["preview"], '"/game/amdnr-linux/run.sh" %command% -novid')
        self.assertEqual(result["removed"], ["Bridge-controlled DXGI override: dxgi=n,b"])

    def test_bridge_removes_stale_dxgi_even_without_old_install_record(self):
        result = launch.preview_bridge_launch(
            'WINEDLLOVERRIDES="dxgi=n,b" VKD3D_DISABLE_EXTENSIONS=VK_EXT_mesh_shader gamemoderun %command%',
            '/game/amdnr-linux/run.sh')
        self.assertEqual(result["compose_status"], "ready")
        self.assertNotIn("WINEDLLOVERRIDES", result["preview"])
        self.assertIn("VKD3D_DISABLE_EXTENSIONS=VK_EXT_mesh_shader gamemoderun", result["preview"])
        self.assertEqual(result["removed"], ["Bridge-controlled DXGI override: dxgi=n,b"])

    def test_bridge_refuses_existing_wrapper_complex_or_unknown_steam_options(self):
        for existing in (
            '"/old/amdnr-linux/run.sh" %command%',
            '%command% && echo hello',
            '%command% %command%',
            'WINEDLLOVERRIDES="x=y" WINEDLLOVERRIDES="a=b" %command%',
        ):
            with self.subTest(existing=existing):
                outcome = launch.preview_bridge_launch(existing, '/game/amdnr-linux/run.sh')
                self.assertIsNone(outcome["preview"])
                self.assertEqual(outcome["compose_status"], "needs_review")
        missing = launch.preview_bridge_launch(None, '/game/amdnr-linux/run.sh')
        self.assertIsNone(missing["preview"])
        self.assertEqual(missing["compose_status"], "unavailable")

    def test_bridge_legacy_wined3d_flag_is_flagged_not_silently_removed(self):
        outcome = launch.preview_bridge_launch(
            'PROTON_USE_WINED3D=1 %command%', '/game/amdnr-linux/run.sh')
        self.assertEqual(outcome["compose_status"], "review")
        self.assertIn('PROTON_USE_WINED3D=1', outcome["preview"])
        self.assertTrue(outcome["review"])

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
