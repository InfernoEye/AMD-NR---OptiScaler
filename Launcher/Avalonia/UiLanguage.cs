using System;
using System.Collections.Generic;
using System.IO;

namespace Amdnr.Linux.Desktop;

/// <summary>
/// User-local launcher UI translations. Does not change the game or Steam.
/// Only strings with vetted Polish equivalents are translated; unknown keys
/// fall back to English rather than displaying machine-guessed text.
/// </summary>
internal static class UiLanguage
{
    private static readonly string PreferencePath = Path.Combine(
        Environment.GetEnvironmentVariable("XDG_CONFIG_HOME")
            ?? Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), ".config"),
        "amdnr-linux", "ui-language.txt");

    private static readonly Dictionary<string, string> Polish = new(StringComparer.Ordinal)
    {
        ["Library"] = "Biblioteka",
        ["Installed"] = "Zainstalowane",
        ["Install"] = "Instalacja",
        ["Doctor"] = "Diagnostyka",
        ["Compatibility"] = "Zgodność",
        ["Settings"] = "Ustawienia",
        ["Help"] = "Pomoc",
        ["Grid"] = "Siatka",
        ["List"] = "Lista",
        ["Refresh"] = "Odśwież",
        ["Your library"] = "Twoja biblioteka",
        ["Search your games…"] = "Szukaj gier…",
        ["Show all"] = "Pokaż wszystkie",
        ["Missing art"] = "Brak okładki",
        ["Add manually"] = "Dodaj ręcznie",
        ["Analyze library"] = "Analizuj bibliotekę",
        ["Rescan library"] = "Skanuj ponownie",
        ["All games"] = "Wszystkie gry",
        ["Windows ready"] = "Gotowe na Windows",
        ["Native Linux"] = "Natywny Linux",
        ["Needs attention"] = "Wymaga uwagi",
        ["AMDNR recorded"] = "AMDNR zarejestrowany",
        ["Select game"] = "Wybierz grę",
        ["Install AMDNR"] = "Zainstaluj AMDNR",
        ["Manage installation"] = "Zarządzaj instalacją",
        ["Configure AMDNR"] = "Konfiguruj AMDNR",
        ["Manage extensions"] = "Zarządzaj rozszerzeniami",
        ["Back to game"] = "Wróć do gry",
        ["All games back"] = "Wszystkie gry",
        ["Change cover art"] = "Zmień okładkę",
        ["Game executable"] = "Plik wykonywalny gry",
        ["Default proxy DLL"] = "Domyślna biblioteka proxy DLL",
        ["Release download directory"] = "Katalog pobierania wydań",
        ["Save preferences"] = "Zapisz preferencje",
        ["Launcher updates"] = "Aktualizacje launchera",
        ["Check for launcher updates"] = "Sprawdź aktualizacje launchera",
        ["Open source & acknowledgements"] = "Otwarte źródła i podziękowania",
        ["Replay introduction"] = "Powtórz wprowadzenie",
        ["Getting started"] = "Pierwsze kroki",
        ["Next"] = "Dalej",
        ["Back"] = "Wstecz",
        ["Finish"] = "Zakończ",
        ["Skip introduction"] = "Pomiń wprowadzenie",
        ["Welcome to AMDNR Linux"] = "Witaj w AMDNR Linux",
        ["Your game library"] = "Twoja biblioteka gier",
        ["Install with control"] = "Instalacja pod Twoją kontrolą",
        ["Repair and diagnostics"] = "Naprawa i diagnostyka",
        ["Linux runtime limitations"] = "Ograniczenia środowiska Linux",
        ["Neural configuration"] = "Konfiguracja neuralna",
        ["Guided settings"] = "Ustawienia z przewodnikiem",
        ["Raw INI editor"] = "Edytor pliku INI",
        ["Save configuration"] = "Zapisz konfigurację",
        ["Reload from disk"] = "Wczytaj ponownie z dysku",
        ["Language"] = "Język",
        ["English"] = "Angielski",
        ["Polish"] = "Polski",
        ["About this launcher"] = "O launcherze",
        ["Troubleshooting"] = "Rozwiązywanie problemów",
        ["Read-only checks"] = "Kontrole tylko do odczytu",
    };

    internal static string Current { get; private set; } = Load();

    internal static string Translate(string key) =>
        Current == "pl" && Polish.TryGetValue(key, out var translation) ? translation : key;

    internal static void Set(string code)
    {
        if (code != "en" && code != "pl")
            throw new ArgumentOutOfRangeException(nameof(code));
        Current = code;
        Directory.CreateDirectory(Path.GetDirectoryName(PreferencePath)!);
        var temporary = PreferencePath + ".tmp";
        File.WriteAllText(temporary, code + "\n");
        File.Move(temporary, PreferencePath, overwrite: true);
    }

    private static string Load()
    {
        try { return File.ReadAllText(PreferencePath).Trim() == "pl" ? "pl" : "en"; }
        catch (IOException) { return "en"; }
        catch (UnauthorizedAccessException) { return "en"; }
    }
}
