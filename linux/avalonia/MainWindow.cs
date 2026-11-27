using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.Primitives;
using Avalonia.Input;
using Avalonia.Layout;
using Avalonia.Media;
using Avalonia.Media.Imaging;
using Avalonia.Platform.Storage;
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Threading.Tasks;

namespace Amdnr.Linux.Desktop;

public sealed class MainWindow : Window
{
    private static readonly IBrush BackgroundBrush = Brush("#0D1119");
    private static readonly IBrush SidebarBrush = Brush("#121A25");
    private static readonly IBrush SurfaceBrush = Brush("#1B2533");
    private static readonly IBrush LineBrush = Brush("#29384C");
    private static readonly IBrush MutedBrush = Brush("#98A9BF");
    private static readonly IBrush ForegroundBrush = Brush("#F3F7FC");
    private static readonly IBrush AccentBrush = Brush("#E04B54");
    private static readonly IBrush AccentDarkBrush = Brush("#59252D");

    private readonly StackPanel _content = new() { Spacing = 16 };
    private readonly TextBlock _status = new() { Text = "Ready", Foreground = MutedBrush };
    private readonly TextBlock _breadcrumb = Text("AMDNR  /  Library", 15, MutedBrush, FontWeight.SemiBold);
    private string _currentSection = "Library";
    private GameEntry? _selectedGame;
    private readonly Dictionary<string, Button> _navigation = new();
    private Backend? _backend;
    private List<GameEntry> _games = new();
    private string? _selectedFolder;
    private string? _exe;
    private string? _archive;
    private string _alias = "dxgi.dll";
    private TextBox? _exeBox;
    private TextBox? _archiveBox;
    private ComboBox? _aliasBox;
    private bool _busy;
    private string _libraryQuery = "";
    private StackPanel? _libraryResults;
    private TextBox? _librarySearch;

    public MainWindow()
    {
        Title = "AMDNR Launcher";
        Width = 1120;
        Height = 750;
        MinWidth = 900;
        MinHeight = 610;
        Background = BackgroundBrush;
        FontFamily = new FontFamily("Inter, Noto Sans, sans-serif");
        WindowStartupLocation = WindowStartupLocation.CenterScreen;

        var app = new Grid { ColumnDefinitions = new ColumnDefinitions("232,*") };
        app.Children.Add(BuildSidebar());
        var main = new Grid { RowDefinitions = new RowDefinitions("76,*,56") };
        Grid.SetColumn(main, 1);
        main.Children.Add(BuildHeader());
        var scroller = new ScrollViewer
        {
            HorizontalScrollBarVisibility = ScrollBarVisibility.Disabled,
            VerticalScrollBarVisibility = ScrollBarVisibility.Auto,
            Content = _content,
            Padding = new Thickness(28, 12, 28, 24),
        };
        Grid.SetRow(scroller, 1);
        main.Children.Add(scroller);
        var statusBorder = new Border
        {
            BorderBrush = LineBrush,
            BorderThickness = new Thickness(0, 1, 0, 0),
            Padding = new Thickness(28, 15, 20, 12),
            Child = _status,
        };
        Grid.SetRow(statusBorder, 2);
        main.Children.Add(statusBorder);
        app.Children.Add(main);
        Content = app;
        try { _backend = new Backend(); }
        catch (Exception ex) { _status.Text = ex.Message; }
        ShowLibrary();
        Opened += async (_, _) => await RefreshGamesAsync();
    }

    private static IBrush Brush(string hex) => new SolidColorBrush(Color.Parse(hex));

    private static TextBlock Text(string text, double size = 14, IBrush? color = null,
        FontWeight? weight = null)
        => new()
        {
            Text = text,
            FontSize = size,
            Foreground = color ?? ForegroundBrush,
            FontWeight = weight ?? FontWeight.Normal,
            TextWrapping = TextWrapping.Wrap,
            VerticalAlignment = VerticalAlignment.Center,
        };

    private static Border Panel(Control child, Thickness? padding = null)
        => new()
        {
            Background = SurfaceBrush,
            BorderBrush = LineBrush,
            BorderThickness = new Thickness(1),
            CornerRadius = new CornerRadius(10),
            Padding = padding ?? new Thickness(20),
            Child = child,
        };

    private static Button Button(string label, bool primary = false)
        => new()
        {
            Content = label,
            Padding = new Thickness(18, 10),
            Background = primary ? AccentBrush : SurfaceBrush,
            Foreground = ForegroundBrush,
            BorderBrush = primary ? AccentBrush : LineBrush,
            BorderThickness = new Thickness(1),
            CornerRadius = new CornerRadius(7),
            HorizontalAlignment = HorizontalAlignment.Left,
        };

    private Control BuildSidebar()
    {
        var stack = new StackPanel { Spacing = 9, Margin = new Thickness(16, 25) };
        stack.Children.Add(Text("AMDNR", 31, AccentBrush, FontWeight.Bold));
        stack.Children.Add(Text("NEURAL RENDERING", 11, MutedBrush, FontWeight.SemiBold));
        stack.Children.Add(new Border { Height = 26 });
        AddNav(stack, "Library", ShowLibrary);
        AddNav(stack, "Install", ShowInstall);
        AddNav(stack, "Doctor", ShowDoctor);
        AddNav(stack, "Settings", ShowSettings);
        stack.Children.Add(new Border { Height = 30 });
        stack.Children.Add(Text("LINUX / PROTON", 11, MutedBrush, FontWeight.Bold));
        stack.Children.Add(Text("Native desktop interface", 12, MutedBrush));
        return new Border
        {
            Background = SidebarBrush,
            BorderBrush = LineBrush,
            BorderThickness = new Thickness(0, 0, 1, 0),
            Child = stack,
        };
    }

    private void AddNav(StackPanel stack, string name, Action action)
    {
        var button = new Button
        {
            Content = name,
            HorizontalContentAlignment = HorizontalAlignment.Left,
            HorizontalAlignment = HorizontalAlignment.Stretch,
            Padding = new Thickness(18, 13),
            Background = Brushes.Transparent,
            Foreground = ForegroundBrush,
            BorderThickness = new Thickness(0),
            CornerRadius = new CornerRadius(8),
        };
        button.Click += (_, _) => { action(); Highlight(name); };
        stack.Children.Add(button);
        _navigation[name] = button;
    }

    private void Highlight(string selected)
    {
        foreach (var (name, button) in _navigation)
        {
            button.Background = name == selected ? SurfaceBrush : Brushes.Transparent;
            button.Foreground = name == selected ? AccentBrush : ForegroundBrush;
        }
    }

    private Control BuildHeader()
    {
        var header = new Grid { ColumnDefinitions = new ColumnDefinitions("*,Auto"), Margin = new Thickness(28, 20, 28, 10) };
        header.Children.Add(_breadcrumb);
        var refresh = Button("↻  Refresh");
        refresh.Click += async (_, _) =>
        {
            // Refresh always returns to the library; it must never reselect a game.
            _selectedGame = null;
            await RefreshGamesAsync();
        };
        Grid.SetColumn(refresh, 1);
        header.Children.Add(refresh);
        return header;
    }

    private void Clear(string section)
    {
        _content.Children.Clear();
        _currentSection = section;
        _breadcrumb.Text = "AMDNR  /  " + section;
        Highlight(section);
    }

    private void ShowLibrary()
    {
        Clear("Library");
        _content.Children.Add(Text("Your games", 30, ForegroundBrush, FontWeight.Bold));
        _content.Children.Add(Text("Detected Steam installations. Choose a game to manage AMDNR.",
            14, MutedBrush));

        var toolbar = new Grid { ColumnDefinitions = new ColumnDefinitions("*,Auto"), ColumnSpacing = 12 };
        _librarySearch = new TextBox
        {
            Text = _libraryQuery,
            Watermark = "Search your games…",
            Background = SurfaceBrush,
            Foreground = ForegroundBrush,
            MinHeight = 42,
        };
        _librarySearch.TextChanged += (_, _) =>
        {
            _libraryQuery = _librarySearch.Text ?? "";
            RenderLibraryResults();
        };
        toolbar.Children.Add(_librarySearch);
        var manual = Button("+  Add manually");
        manual.Click += (_, _) => ShowInstall();
        Grid.SetColumn(manual, 1);
        toolbar.Children.Add(manual);
        _content.Children.Add(toolbar);

        _libraryResults = new StackPanel { Spacing = 12 };
        _content.Children.Add(_libraryResults);
        RenderLibraryResults();
    }

    private void RenderLibraryResults()
    {
        if (_libraryResults is null) return;
        _libraryResults.Children.Clear();
        var filtered = _games.Where(game =>
            game.Name.Contains(_libraryQuery, StringComparison.OrdinalIgnoreCase) ||
            game.Folder.Contains(_libraryQuery, StringComparison.OrdinalIgnoreCase)).ToList();
        _libraryResults.Children.Add(Text(
            $"{filtered.Count} of {_games.Count} games", 12, AccentBrush, FontWeight.SemiBold));

        if (filtered.Count == 0)
        {
            var empty = new StackPanel { Spacing = 12 };
            empty.Children.Add(Text(_games.Count == 0 ? "No Steam games detected" : "No matching games",
                20, ForegroundBrush, FontWeight.SemiBold));
            empty.Children.Add(Text(_games.Count == 0
                ? "Check Steam's library folders, refresh, or choose an executable manually."
                : "Try searching for a shorter name or clear the search field.", 13, MutedBrush));
            var action = Button(_games.Count == 0 ? "Choose an executable" : "Clear search", true);
            action.Click += (_, _) =>
            {
                if (_games.Count == 0) ShowInstall();
                else if (_librarySearch is not null) _librarySearch.Text = "";
            };
            empty.Children.Add(action);
            _libraryResults.Children.Add(Panel(empty));
            return;
        }

        // Windows-style, game-focused single-column rows with full-width action area.
        foreach (var game in filtered)
            _libraryResults.Children.Add(BuildGameCard(game));
    }

    private Control BuildGameCard(GameEntry game)
    {
        var row = new Grid { ColumnDefinitions = new ColumnDefinitions("138,*,Auto"), ColumnSpacing = 18 };
        var illustration = GameArtwork(game, 110);
        row.Children.Add(illustration);

        var detail = new StackPanel { Spacing = 7, VerticalAlignment = VerticalAlignment.Center };
        detail.Children.Add(Text(game.Name, 19, ForegroundBrush, FontWeight.SemiBold));
        detail.Children.Add(Text("STEAM  ·  PROTON / WINE", 11, MutedBrush, FontWeight.SemiBold));
        var location = Text(game.Folder, 12, MutedBrush);
        location.MaxLines = 2;
        detail.Children.Add(location);
        Grid.SetColumn(detail, 1);
        row.Children.Add(detail);

        var manage = Button("SELECT GAME  →", true);
        manage.VerticalAlignment = VerticalAlignment.Center;
        manage.Click += (_, _) => SelectGame(game);
        Grid.SetColumn(manage, 2);
        row.Children.Add(manage);
        return Panel(row, new Thickness(15));
    }

    private Control GameArtwork(GameEntry game, double height)
    {
        var illustration = new Grid { Height = height };
        illustration.Children.Add(new Border
        {
            Background = SidebarBrush,
            CornerRadius = new CornerRadius(8),
        });
        illustration.Children.Add(new TextBlock
        {
            Text = game.Name.Length > 0 ? game.Name[..1].ToUpperInvariant() : "?",
            FontSize = 48,
            FontWeight = FontWeight.Bold,
            Foreground = AccentBrush,
            HorizontalAlignment = HorizontalAlignment.Center,
            VerticalAlignment = VerticalAlignment.Center,
        });
        if (!string.IsNullOrEmpty(game.Artwork))
        {
            try
            {
                // Decode first; if the cache is corrupt retain the letter placeholder.
                var bitmap = new Bitmap(game.Artwork);
                illustration.Children.Clear();
                illustration.Children.Add(new Border
                {
                    CornerRadius = new CornerRadius(8),
                    ClipToBounds = true,
                    Child = new Image
                    {
                        Source = bitmap,
                        Stretch = Stretch.Uniform,
                        HorizontalAlignment = HorizontalAlignment.Stretch,
                        VerticalAlignment = VerticalAlignment.Stretch,
                    },
                });
            }
            catch (Exception ex) when (ex is IOException or ArgumentException or
                                       UnauthorizedAccessException or NotSupportedException)
            {
                // Steam can remove its cached image during a session.
            }
        }
        return illustration;
    }

    private void SelectGame(GameEntry game)
    {
        _selectedGame = game;
        _selectedFolder = game.Folder;
        _exe = GuessExecutable(game.Folder);
        _status.Text = _exe is null
            ? $"Selected {game.Name}; choose the Windows executable manually."
            : $"Selected {game.Name}: {_exe}";
        ShowGameDetails();
    }

    private bool HasInstallRecord()
        => !string.IsNullOrWhiteSpace(_exe) &&
           File.Exists(Path.Combine(Path.GetDirectoryName(_exe)!, ".amdnr-linux-install.json"));

    private void ShowGameDetails()
    {
        if (_selectedGame is not { } game) { ShowLibrary(); return; }
        Clear("Library");
        _breadcrumb.Text = "AMDNR  /  Library  /  " + game.Name;

        var back = Button("←  ALL GAMES");
        back.Click += (_, _) => ShowLibrary();
        _content.Children.Add(back);

        var hero = new Grid { ColumnDefinitions = new ColumnDefinitions("240,*"), ColumnSpacing = 24 };
        hero.Children.Add(GameArtwork(game, 245));
        var summary = new StackPanel { Spacing = 14, VerticalAlignment = VerticalAlignment.Center };
        summary.Children.Add(Text("STEAM  /  PROTON", 12, AccentBrush, FontWeight.SemiBold));
        summary.Children.Add(Text(game.Name, 31, ForegroundBrush, FontWeight.Bold));
        bool installed = HasInstallRecord();
        summary.Children.Add(Text(installed ? "●  AMDNR installation recorded" :
            "○  No AMDNR installation recorded for selected executable", 13,
            installed ? AccentBrush : MutedBrush));
        summary.Children.Add(Text(game.Folder, 12, MutedBrush));
        var actions = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 12 };
        var install = Button(installed ? "MANAGE INSTALLATION" : "INSTALL AMDNR", true);
        install.Click += (_, _) => ShowInstall();
        actions.Children.Add(install);
        var doctor = Button("DOCTOR");
        doctor.Click += (_, _) => ShowDoctor();
        actions.Children.Add(doctor);
        summary.Children.Add(actions);
        var coverButton = Button("CHANGE COVER ART");
        coverButton.Click += async (_, _) =>
        {
            var image = await PickFileAsync("Select game artwork (JPG / PNG)",
                new FilePickerFileType("Images")
                {
                    Patterns = new[] { "*.jpg", "*.jpeg", "*.png" },
                });
            if (image is null || _backend is null) return;
            _status.Text = "Saving custom artwork…";
            try
            {
                var (exit, message) = await _backend.RunAsync(new[]
                {
                    "--set-artwork", image, "--game-folder", game.Folder,
                });
                if (exit != 0) { _status.Text = message; return; }
                _status.Text = "Cover saved. Refresh the library to display it.";
                await RefreshGamesAsync();
            }
            catch (Exception ex) { _status.Text = "Cover update failed: " + ex.Message; }
        };
        summary.Children.Add(coverButton);
        Grid.SetColumn(summary, 1);
        hero.Children.Add(summary);
        _content.Children.Add(Panel(hero, new Thickness(22)));

        var detail = new StackPanel { Spacing = 13 };
        detail.Children.Add(Text("GAME CONFIGURATION", 12, AccentBrush, FontWeight.Bold));
        detail.Children.Add(Text("Executable", 12, MutedBrush));
        var exeLine = new TextBox
        {
            Text = _exe ?? "", Watermark = "Select the game EXE to enable installation",
            Background = BackgroundBrush, Foreground = ForegroundBrush,
        };
        exeLine.TextChanged += (_, _) => _exe = exeLine.Text;
        detail.Children.Add(exeLine);
        var selectExe = Button("CHANGE EXECUTABLE");
        selectExe.Click += async (_, _) =>
        {
            var selected = await PickFileAsync("Select game executable",
                new FilePickerFileType("Windows executable") { Patterns = new[] { "*.exe" } });
            if (selected is not null)
            {
                exeLine.Text = selected;
                ShowGameDetails();
            }
        };
        detail.Children.Add(selectExe);
        detail.Children.Add(Text("Install status is based on the Linux launcher's installation " +
            "record beside the selected executable. Existing installations made by other tools " +
            "may not be detected.", 12, MutedBrush));
        _content.Children.Add(Panel(detail));
    }

    private static string? GuessExecutable(string folder)
    {
        // This is a hint, not an automatic install destination; user can replace it.
        try
        {
            return Directory.EnumerateFiles(folder, "*.exe", SearchOption.AllDirectories)
                .Where(path => path.Split(Path.DirectorySeparatorChar).Length
                    - folder.Split(Path.DirectorySeparatorChar).Length <= 6)
                .Where(path => !new[] { "unins", "setup", "crash", "redist", "anticheat",
                                        "updater", "vcredist" }.Any(part =>
                    Path.GetFileName(path).Contains(part, StringComparison.OrdinalIgnoreCase)))
                .OrderBy(path => path.Length)
                .FirstOrDefault();
        }
        catch (Exception) { return null; }
    }

    private void ShowInstall()
    {
        Clear("Install");
        _content.Children.Add(Text("Install & manage", 30, ForegroundBrush, FontWeight.Bold));
        _content.Children.Add(Text("Manage AMDNR files alongside your Windows game executable. " +
            "Select a trusted release ZIP and a proxy DLL name.", 14, MutedBrush));

        var section = new StackPanel { Spacing = 14 };
        section.Children.Add(Text("GAME EXECUTABLE", 11, MutedBrush, FontWeight.Bold));
        var exeRow = new Grid { ColumnDefinitions = new ColumnDefinitions("*,Auto"), ColumnSpacing = 10 };
        _exeBox = new TextBox
        {
            Text = _exe ?? "", Watermark = "/path/to/game/Binaries/Win64/Game.exe",
            Background = BackgroundBrush, Foreground = ForegroundBrush,
        };
        _exeBox.TextChanged += (_, _) => _exe = _exeBox.Text;
        exeRow.Children.Add(_exeBox);
        var browseExe = Button("Browse");
        browseExe.Click += async (_, _) =>
        {
            var selected = await PickFileAsync("Select the Windows game executable",
                new FilePickerFileType("Windows executable") { Patterns = new[] { "*.exe" } });
            if (selected is not null) _exeBox.Text = selected;
        };
        Grid.SetColumn(browseExe, 1);
        exeRow.Children.Add(browseExe);
        section.Children.Add(exeRow);

        section.Children.Add(Text("RELEASE ARCHIVE", 11, MutedBrush, FontWeight.Bold));
        var archiveRow = new Grid { ColumnDefinitions = new ColumnDefinitions("*,Auto"), ColumnSpacing = 10 };
        _archiveBox = new TextBox
        {
            Text = _archive ?? "", Watermark = "/path/to/AMDNR-release.zip",
            Background = BackgroundBrush, Foreground = ForegroundBrush,
        };
        _archiveBox.TextChanged += (_, _) => _archive = _archiveBox.Text;
        archiveRow.Children.Add(_archiveBox);
        var browseZip = Button("Browse");
        browseZip.Click += async (_, _) =>
        {
            var selected = await PickFileAsync("Choose a trusted AMDNR release ZIP",
                new FilePickerFileType("ZIP archive") { Patterns = new[] { "*.zip" } });
            if (selected is not null) _archiveBox.Text = selected;
        };
        Grid.SetColumn(browseZip, 1);
        archiveRow.Children.Add(browseZip);
        section.Children.Add(archiveRow);

        section.Children.Add(Text("PROXY DLL NAME", 11, MutedBrush, FontWeight.Bold));
        var aliases = new[] { "dxgi.dll", "version.dll", "winmm.dll", "winhttp.dll",
            "wininet.dll", "dbghelp.dll", "d3d12.dll", "OptiScaler.asi" };
        _aliasBox = new ComboBox
        {
            ItemsSource = aliases,
            SelectedItem = _alias,
            Width = 220,
            HorizontalAlignment = HorizontalAlignment.Left,
        };
        _aliasBox.SelectionChanged += (_, _) => _alias = _aliasBox.SelectedItem?.ToString() ?? "dxgi.dll";
        section.Children.Add(_aliasBox);
        var buttons = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 12 };
        var installButton = Button("Install AMDNR", true);
        installButton.Click += async (_, _) => await ExecuteAsync(true);
        var uninstallButton = Button("Uninstall / restore");
        uninstallButton.Click += async (_, _) => await ExecuteAsync(false);
        buttons.Children.Add(installButton);
        buttons.Children.Add(uninstallButton);
        section.Children.Add(buttons);
        _content.Children.Add(Panel(section));

        var help = new StackPanel { Spacing = 8 };
        help.Children.Add(Text("Proton launch options", 18, ForegroundBrush, FontWeight.Bold));
        help.Children.Add(Text(_alias.EndsWith(".asi", StringComparison.OrdinalIgnoreCase)
            ? "ASI plugins require a compatible ASI loader."
            : $"WINEDLLOVERRIDES=\"{Path.GetFileNameWithoutExtension(_alias).ToLowerInvariant()}=n,b\" %command%",
            14, AccentBrush));
        var copyOverride = Button("Copy launch options");
        copyOverride.Click += async (_, _) =>
        {
            if (Clipboard is null) return;
            if (_alias.EndsWith(".asi", StringComparison.OrdinalIgnoreCase))
            {
                _status.Text = "ASI plugins require a compatible loader; no DLL override to copy.";
                return;
            }
            var value = $"WINEDLLOVERRIDES=\"{Path.GetFileNameWithoutExtension(_alias).ToLowerInvariant()}=n,b\" %command%";
            await Clipboard.SetTextAsync(value);
            _status.Text = "Steam launch options copied to clipboard.";
        };
        help.Children.Add(copyOverride);
        help.Children.Add(Text("Set the override in Steam → Properties → General → Launch Options. " +
            "Some games or anti-cheat configurations may reject DLL injection.", 13, MutedBrush));
        _content.Children.Add(Panel(help));
    }

    private async Task<string?> PickFileAsync(string title, FilePickerFileType filter)
    {
        var files = await StorageProvider.OpenFilePickerAsync(new FilePickerOpenOptions
        {
            Title = title, AllowMultiple = false, FileTypeFilter = new[] { filter },
        });
        return files.FirstOrDefault()?.TryGetLocalPath();
    }

    private async Task ExecuteAsync(bool install)
    {
        if (_busy) return;
        if (_backend is null)
        {
            _status.Text = "Linux backend not found; see linux/README.md";
            return;
        }
        if (string.IsNullOrWhiteSpace(_exe) || !File.Exists(_exe))
        {
            _status.Text = "Select an existing Windows game executable first.";
            return;
        }
        if (install && (string.IsNullOrWhiteSpace(_archive) || !File.Exists(_archive)))
        {
            _status.Text = "Select an existing AMDNR release ZIP first.";
            return;
        }
        _busy = true;
        _status.Text = install ? "Installing AMDNR…" : "Restoring backups…";
        try
        {
            var args = install
                ? new[] { "--install", _archive!, "--exe", _exe!, "--alias", _alias }
                : new[] { "--uninstall", "--exe", _exe! };
            var (exit, output) = await _backend.RunAsync(args);
            _status.Text = exit == 0 ? output : $"Operation returned {exit}: {output}";
        }
        catch (Exception ex) { _status.Text = $"Operation failed: {ex.Message}"; }
        finally { _busy = false; }
    }

    private void ShowDoctor()
    {
        Clear("Doctor");
        _content.Children.Add(Text("Doctor", 30, ForegroundBrush, FontWeight.Bold));
        _content.Children.Add(Text("Environment and installation checks for Steam/Proton.",
            14, MutedBrush));
        var checks = new StackPanel { Spacing = 14 };
        var lines = new List<(string, bool)>
        {
            ("Linux desktop", OperatingSystem.IsLinux()),
            ("Python 3 backend", _backend is not null),
            ("Steam library discovered", _games.Count > 0),
            ("Selected game executable", _exe is not null && File.Exists(_exe)),
            ("Selected release archive", _archive is not null && File.Exists(_archive)),
        };
        foreach (var (name, okay) in lines)
        {
            var row = new Grid { ColumnDefinitions = new ColumnDefinitions("Auto,*"), ColumnSpacing = 12 };
            row.Children.Add(Text(okay ? "✓" : "!", 18, okay ? AccentBrush : MutedBrush));
            var info = Text(name, 15);
            Grid.SetColumn(info, 1);
            row.Children.Add(info);
            checks.Children.Add(row);
        }
        _content.Children.Add(Panel(checks));
        _content.Children.Add(Text("These are launcher-environment checks, not a verification of " +
            "GPU compatibility, rendering quality, or the Windows DLL runtime under Proton.",
            13, MutedBrush));
    }

    private void ShowSettings()
    {
        Clear("Settings");
        _content.Children.Add(Text("Settings", 30, ForegroundBrush, FontWeight.Bold));
        var details = new StackPanel { Spacing = 10 };
        details.Children.Add(Text("Linux integration", 18, ForegroundBrush, FontWeight.Bold));
        details.Children.Add(Text("The native desktop interface uses the independent Python " +
            "installation backend. Use AMDNR_LINUX_BACKEND to set a custom backend path.",
            14, MutedBrush));
        details.Children.Add(Text("Downloads and updates are intentionally manual in this build. " +
            "Use a trusted AMDNR release archive.", 14, MutedBrush));
        _content.Children.Add(Panel(details));
    }

    private async Task RefreshGamesAsync()
    {
        if (_busy || _backend is null) return;
        _busy = true;
        _status.Text = "Scanning Steam libraries…";
        try
        {
            _games = (await _backend.GamesAsync()).ToList();
            _status.Text = $"Detected {_games.Count} Steam games";
            // Scan changes should update the list, not navigate to a selected game.
            // Keep this deterministic even if the previous page was Game Details.
            if (_currentSection == "Library")
                ShowLibrary();
        }
        catch (Exception ex) { _status.Text = $"Steam scan failed: {ex.Message}"; }
        finally { _busy = false; }
    }
}
