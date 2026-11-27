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
        ["Save settings"] = "Zapisz ustawienia",
        ["Save configuration"] = "Zapisz konfigurację",
        ["Reload from disk"] = "Wczytaj ponownie z dysku",
        ["Browse"] = "Przeglądaj",
        ["Browse exe"] = "Wybierz EXE",
        ["Rescan"] = "Skanuj ponownie",
        ["Use this executable"] = "Użyj tego pliku EXE",
        ["Quick install latest verified AMDNR"] = "Szybko zainstaluj najnowszy sprawdzony AMDNR",
        ["Download selected zip"] = "Pobierz wybrany ZIP",
        ["Load builds"] = "Wczytaj wersje",
        ["Check available versions"] = "Sprawdź dostępne wersje",
        ["Verify all installed files"] = "Sprawdź wszystkie zainstalowane pliki",
        ["Check file integrity"] = "Sprawdź integralność plików",
        ["Repair"] = "Napraw",
        ["Repair automatically"] = "Napraw automatycznie",
        ["Uninstall"] = "Odinstaluj",
        ["Confirm removal"] = "Potwierdź usunięcie",
        ["Cancel"] = "Anuluj",
        ["Select release"] = "Wybierz wydanie",
        ["Download verified AppImage"] = "Pobierz sprawdzony AppImage",
        ["Install downloaded AppImage"] = "Zainstaluj pobrany AppImage",
        ["View AMDNR-Linux research"] = "Zobacz badania AMDNR-Linux",
        ["Show prerelease builds in the release picker"] = "Pokazuj wersje testowe w wyborze wydań",
        ["Edit / remove custom game"] = "Edytuj / usuń grę niestandardową",
        ["Change executable"] = "Zmień plik EXE",
        ["Apply language"] = "Zastosuj język",
        ["Preview this change"] = "Podgląd zmiany",
        ["Manage plugins"] = "Zarządzaj wtyczkami",
        ["Import local .asi"] = "Importuj lokalny plik .asi",
        ["Save to library"] = "Zapisz w bibliotece",
        ["Edit custom game"] = "Edytuj grę niestandardową",
        ["Back to library"] = "Wróć do biblioteki",
    };

    internal static string Current { get; private set; } = Load();

    internal static string Translate(string key) =>
        Current == "pl" && Polish.TryGetValue(key, out var translation) ? translation : key;

    internal static string TranslateButton(string label)
    {
        if (Current != "pl") return label;
        if (Polish.TryGetValue(label, out var direct)) return direct;
        // Match uppercase action labels without altering identifiers, filenames,
        // Steam launch options or other user-supplied values.
        foreach (var pair in Polish)
        {
            if (string.Equals(label, pair.Key.ToUpperInvariant(), StringComparison.Ordinal))
                return pair.Value.ToUpperInvariant();
        }
        return label;
    }

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
