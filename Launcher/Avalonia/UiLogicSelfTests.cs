using System;
using System.Linq;

namespace Amdnr.Linux.Desktop;

/// <summary>
/// Dependency-free behavioral smoke checks for guided INI changes.
/// Run: dotnet run --project Launcher/Avalonia/Amdnr.Avalonia.csproj -- --selftest-ui
/// Does not start the UI, modify a game, or read/write launcher preferences.
/// </summary>
internal static class UiLogicSelfTests
{
    internal static int Run()
    {
        try
        {
            CheckIniPreservation();
            CheckInvalidChangeRefused();
            CheckDuplicateKeysIgnored();
            CheckLanguageFallback();
            Console.WriteLine("UI logic self-tests passed.");
            return 0;
        }
        catch (Exception error)
        {
            Console.Error.WriteLine("UI logic self-test FAILED: " + error);
            return 1;
        }
    }

    private static void Assert(bool condition, string message)
    {
        if (!condition) throw new InvalidOperationException(message);
    }

    private static void CheckIniPreservation()
    {
        var original = "; existing comment\r\n[DlssNr]\r\n" +
            "AmdLmxxfFastMode=true ; existing note\r\n" +
            "OtherKey=leave this exactly intact\r\n\r\n[Other]\r\n" +
            "AmdLmxxfFastMode=true\r\n";
        var setting = GuidedIniEditor.Read(original).Single();
        Assert(setting.Key == "AmdLmxxfFastMode", "Known key not discovered");
        var changed = GuidedIniEditor.PreviewChange(original, setting, "false");
        Assert(changed.Contains("AmdLmxxfFastMode=false ; existing note", StringComparison.Ordinal),
            "Setting was not changed or its inline comment was lost");
        Assert(changed.Contains("OtherKey=leave this exactly intact\r\n\r\n[Other]", StringComparison.Ordinal),
            "Unrelated keys or line endings changed");
        Assert(changed.EndsWith("[Other]\r\nAmdLmxxfFastMode=true\r\n", StringComparison.Ordinal),
            "Identical key in another section changed");
    }

    private static void CheckInvalidChangeRefused()
    {
        var input = "[DlssNr]\nAmdPlacement=pre\n";
        var setting = GuidedIniEditor.Read(input).Single();
        try
        {
            _ = GuidedIniEditor.PreviewChange(input, setting, "unsupported");
            throw new InvalidOperationException("Unsupported value accepted");
        }
        catch (ArgumentException) { }
        try
        {
            _ = GuidedIniEditor.PreviewChange("[DlssNr]\nAmdPlacement=post\n", setting, "post");
            throw new InvalidOperationException("Stale INI preview accepted");
        }
        catch (InvalidOperationException ex) when (ex.Message.Contains("changed", StringComparison.Ordinal)) { }
    }

    private static void CheckDuplicateKeysIgnored()
    {
        var input = "[DlssNr]\nAmdFaceDetail=true\nAmdFaceDetail=false\n";
        Assert(GuidedIniEditor.Read(input).Count == 0,
            "Ambiguous duplicate key was not excluded from guided editing");
    }

    private static void CheckLanguageFallback()
    {
        const string unknown = "an_untranslated_future_key";
        Assert(UiLanguage.Translate(unknown) == unknown, "Unknown localization key was changed");
    }
}
