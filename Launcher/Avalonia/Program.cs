using Avalonia;
using System;

namespace Amdnr.Linux.Desktop;

internal static class Program
{
    [STAThread]
    public static void Main(string[] args)
    {
        if (Array.Exists(args, arg => arg == "--selftest-ui"))
        {
            Environment.ExitCode = UiLogicSelfTests.Run();
            return;
        }
        BuildAvaloniaApp().StartWithClassicDesktopLifetime(args);
    }

    public static AppBuilder BuildAvaloniaApp()
        => AppBuilder.Configure<App>().UsePlatformDetect().LogToTrace();
}
