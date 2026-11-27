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
using System.Text.Json;

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

    private readonly StackPanel _content = new() { Spacing = 14 };
    private readonly ScrollViewer _pageScroller;
    private readonly TextBlock _status = new() { Text = "Ready", Foreground = MutedBrush };
    private readonly TextBlock _breadcrumb = Text("AMDNR  /  Library", 15, MutedBrush, FontWeight.SemiBold);
    private string _currentSection = "Library";
    private GameEntry? _selectedGame;
    private IReadOnlyList<ExecutableEntry> _exeCandidates = Array.Empty<ExecutableEntry>();
    private bool _showAlternativeExecutables;
    private readonly Dictionary<string, Button> _navigation = new();
    private Backend? _backend;
    private List<GameEntry> _games = new();
    private string? _selectedFolder;
    private string? _exe;
    private string? _archive;
    private string _alias = "dxgi.dll";
    private TextBox? _exeBox;
    private TextBox? _archiveBox;
    private TextBlock? _installationStatus;
    private Button? _installAction;
    private Button? _uninstallAction;
    private ComboBox? _aliasBox;
    private bool _busy;
    private string _libraryQuery = "";
    private bool _missingArtOnly;
    private StackPanel? _libraryResults;
    private TextBox? _librarySearch;

    public MainWindow()
    {
        Title = "AMDNR Launcher";
        Width = 1120;
        Height = 750;
        MinWidth = 900;
        MinHeight = 480;
        // Never change window bounds in response to content changes.
        SizeToContent = SizeToContent.Manual;
        Background = BackgroundBrush;
        FontFamily = new FontFamily("Inter, Noto Sans, sans-serif");
        WindowStartupLocation = WindowStartupLocation.CenterScreen;

        var app = new Grid { ColumnDefinitions = new ColumnDefinitions("232,*") };
        app.Children.Add(BuildSidebar());
        // Status lives in the header; the content viewport must never sit behind a footer.
        var main = new Grid { RowDefinitions = new RowDefinitions("90,*") };
        Grid.SetColumn(main, 1);
        main.Children.Add(BuildHeader());
        // The trailing spacer is real scroll content, not ScrollViewer padding.
        // It guarantees the final controls can scroll well above the window edge.
        var scrollBody = new StackPanel { Spacing = 0 };
        scrollBody.Children.Add(_content);
        scrollBody.Children.Add(new Border { Height = 140, IsHitTestVisible = false });
        _pageScroller = new ScrollViewer
        {
            HorizontalScrollBarVisibility = ScrollBarVisibility.Disabled,
            VerticalScrollBarVisibility = ScrollBarVisibility.Auto,
            Content = scrollBody,
            Padding = new Thickness(28, 10, 28, 12),
        };
        Grid.SetRow(_pageScroller, 1);
        main.Children.Add(_pageScroller);
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
        var header = new Grid
        {
            ColumnDefinitions = new ColumnDefinitions("*,Auto"),
            RowDefinitions = new RowDefinitions("Auto,Auto"),
            RowSpacing = 5,
            Margin = new Thickness(28, 13, 28, 10),
        };
        header.Children.Add(_breadcrumb);
        _status.FontSize = 12;
        _status.MaxLines = 1;
        _status.TextTrimming = TextTrimming.CharacterEllipsis;
        _status.VerticalAlignment = VerticalAlignment.Center;
        Grid.SetRow(_status, 1);
        header.Children.Add(_status);
        var refresh = Button("↻  Refresh");
        refresh.VerticalAlignment = VerticalAlignment.Center;
        Grid.SetRowSpan(refresh, 2);
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
        // Navigation returns to the beginning of the new page; user-sized
        // window dimensions are intentionally unchanged.
        _pageScroller.Offset = new Vector(0, 0);
    }

    private void ShowLibrary()
    {
        Clear("Library");
        _content.Children.Add(Text("Your games", 30, ForegroundBrush, FontWeight.Bold));
        _content.Children.Add(Text("Detected Steam installations. Choose a game to manage AMDNR.",
            14, MutedBrush));

        var toolbar = new Grid { ColumnDefinitions = new ColumnDefinitions("*,Auto,Auto"), ColumnSpacing = 12 };
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
        var missing = Button(_missingArtOnly ? "SHOW ALL" : "MISSING ART");
        missing.Click += (_, _) =>
        {
            _missingArtOnly = !_missingArtOnly;
            ShowLibrary();
        };
        Grid.SetColumn(missing, 1);
        toolbar.Children.Add(missing);
        var manual = Button("+  Add manually");
        manual.Click += (_, _) => ShowInstall();
        Grid.SetColumn(manual, 2);
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
            (!_missingArtOnly || string.IsNullOrEmpty(game.Artwork)) &&
            (game.Name.Contains(_libraryQuery, StringComparison.OrdinalIgnoreCase) ||
             game.Folder.Contains(_libraryQuery, StringComparison.OrdinalIgnoreCase))).ToList();
        var missingCount = _games.Count(game => string.IsNullOrEmpty(game.Artwork));
        _libraryResults.Children.Add(Text(
            $"{filtered.Count} of {_games.Count} games  •  {missingCount} covers missing",
            12, AccentBrush, FontWeight.SemiBold));

        if (filtered.Count == 0)
        {
            var empty = new StackPanel { Spacing = 12 };
            empty.Children.Add(Text(_games.Count == 0 ? "No Steam games detected" : "No matching games",
                20, ForegroundBrush, FontWeight.SemiBold));
            empty.Children.Add(Text(_games.Count == 0
                ? "Check Steam's library folders, refresh, or choose an executable manually."
                : _missingArtOnly ? "All visible games have covers. Choose SHOW ALL to return." :
                    "Try searching for a shorter name or clear the search field.", 13, MutedBrush));
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
        // Always have useful artwork, even when Steam has no published capsule.
        // Generated locally from the game title: no name-based exceptions or extra APIs.
        var placeholder = new Grid { RowDefinitions = new RowDefinitions("Auto,*,Auto") };
        var artBackground = new Border
        {
            Background = Brush("#30202C"),
            BorderBrush = AccentDarkBrush,
            BorderThickness = new Thickness(1),
            CornerRadius = new CornerRadius(8),
        };
        Grid.SetRowSpan(artBackground, 3);
        placeholder.Children.Add(artBackground);
        var top = Text("AMDNR  /  LIBRARY", 10, AccentBrush, FontWeight.Bold);
        top.Margin = new Thickness(12, 11, 12, 0);
        placeholder.Children.Add(top);
        var title = Text(game.Name, height >= 200 ? 25 : 16,
            ForegroundBrush, FontWeight.Bold);
        title.Margin = new Thickness(12, 4, 12, 4);
        title.MaxLines = height >= 200 ? 4 : 3;
        Grid.SetRow(title, 1);
        placeholder.Children.Add(title);
        var bottom = Text("STEAM  ·  COVER NOT AVAILABLE", 9, MutedBrush);
        bottom.Margin = new Thickness(12, 0, 12, 10);
        Grid.SetRow(bottom, 2);
        placeholder.Children.Add(bottom);
        illustration.Children.Add(new Border
        {
            Child = placeholder,
            Background = SidebarBrush,
            CornerRadius = new CornerRadius(8),
            ClipToBounds = true,
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

    private async void SelectGame(GameEntry game)
    {
        if (_busy) return;
        _selectedGame = game;
        _selectedFolder = game.Folder;
        _exe = null;
        _exeCandidates = Array.Empty<ExecutableEntry>();
        _showAlternativeExecutables = false;
        ShowGameDetails();
        await FindExecutablesAsync(game);
    }

    private async Task FindExecutablesAsync(GameEntry game)
    {
        if (_backend is null || _busy) return;
        _busy = true;
        _status.Text = "Finding game executable candidates…";
        try
        {
            var results = await _backend.ExecutablesAsync(game.Folder);
            // Do not navigate to a different game after an asynchronous scan.
            if (_selectedGame?.Folder != game.Folder) return;
            _exeCandidates = results;
            var saved = await _backend.SavedExecutableAsync(game.Folder);
            if (_selectedGame?.Folder != game.Folder) return;
            var chosen = saved ?? results.FirstOrDefault(e => e.AutoSelect)?.Path;
            _exe = chosen;
            _status.Text = saved is not null
                ? "Restored saved executable: " + Path.GetFileName(saved)
                : chosen is not null
                    ? "Automatically selected likely game executable: " + Path.GetFileName(chosen)
                    : results.Count == 0
                        ? "No Windows executable detected. Choose one manually."
                        : "Several possible executables found. Select the correct one.";
            ShowGameDetails();
        }
        catch (Exception ex) { _status.Text = "Executable scan failed: " + ex.Message; }
        finally { _busy = false; }
    }

    private async Task ConfirmExecutableAsync(string path)
    {
        if (_selectedGame is not { } game || _backend is null) return;
        if (!File.Exists(path) || !path.EndsWith(".exe", StringComparison.OrdinalIgnoreCase))
        {
            _status.Text = "Selected executable is no longer available.";
            return;
        }
        try
        {
            await _backend.RememberExecutableAsync(game.Folder, path);
            if (_selectedGame?.Folder != game.Folder) return;
            _exe = path;
            _status.Text = "Saved executable preference: " + Path.GetFileName(path);
            ShowGameDetails();
        }
        catch (Exception ex) { _status.Text = "Could not save executable choice: " + ex.Message; }
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

        var hero = new Grid { ColumnDefinitions = new ColumnDefinitions("205,*"), ColumnSpacing = 20 };
        hero.Children.Add(GameArtwork(game, 190));
        var summary = new StackPanel { Spacing = 10, VerticalAlignment = VerticalAlignment.Center };
        summary.Children.Add(Text("STEAM  /  PROTON", 12, AccentBrush, FontWeight.SemiBold));
        summary.Children.Add(Text(game.Name, 31, ForegroundBrush, FontWeight.Bold));
        bool installed = HasInstallRecord();
        summary.Children.Add(Text(installed ? "●  AMDNR installation recorded" :
            "○  No AMDNR installation recorded for selected executable", 13,
            installed ? AccentBrush : MutedBrush));
        summary.Children.Add(Text(game.Folder, 12, MutedBrush));
        var actions = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 12 };
        var install = Button(installed ? "MANAGE INSTALLATION" : "INSTALL AMDNR", true);
        install.IsEnabled = _exe is not null && File.Exists(_exe);
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
        detail.Children.Add(Text("GAME EXECUTABLE", 12, AccentBrush, FontWeight.Bold));
        var recommended = _exeCandidates.FirstOrDefault(e => e.Recommended);
        var chosen = _exe;

        if (!string.IsNullOrWhiteSpace(chosen) && File.Exists(chosen))
        {
            var selected = new StackPanel { Spacing = 5 };
            selected.Children.Add(Text("✓  Selected game executable · change anytime", 15,
                AccentBrush, FontWeight.SemiBold));
            selected.Children.Add(Text(Path.GetFileName(chosen), 20,
                ForegroundBrush, FontWeight.SemiBold));
            selected.Children.Add(Text(Path.GetRelativePath(game.Folder, chosen), 12, MutedBrush));
            detail.Children.Add(Panel(selected, new Thickness(14)));
        }
        else if (recommended is not null)
        {
            var suggestion = new StackPanel { Spacing = 9 };
            suggestion.Children.Add(Text("★  Recommended executable · not yet confirmed",
                13, AccentBrush, FontWeight.SemiBold));
            suggestion.Children.Add(Text(Path.GetFileName(recommended.Path), 20,
                ForegroundBrush, FontWeight.SemiBold));
            suggestion.Children.Add(Text(Path.GetRelativePath(game.Folder, recommended.Path),
                13, MutedBrush));
            var confirm = Button("USE THIS EXECUTABLE", true);
            confirm.Click += async (_, _) => await ConfirmExecutableAsync(recommended.Path);
            suggestion.Children.Add(confirm);
            detail.Children.Add(Panel(suggestion, new Thickness(14)));
        }
        else
        {
            detail.Children.Add(Text(_busy ? "Scanning game folder for Windows executables…"
                : "No executable confirmed. Find or browse to the game EXE.",
                14, MutedBrush));
        }

        detail.Children.Add(Text("Likely game executables are selected automatically. " +
            "Your manual choice is remembered per game. Check the path before installing.", 12, MutedBrush));

        var exeActions = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 10 };
        var alternatives = _exeCandidates.Where(e => e.Path != chosen &&
            e.Path != recommended?.Path).ToList();
        if (alternatives.Count > 0 || (recommended is not null && chosen != recommended.Path))
        {
            var toggle = Button(_showAlternativeExecutables
                ? "HIDE ALTERNATIVES" : $"CHANGE EXECUTABLE ({_exeCandidates.Count})");
            toggle.Click += (_, _) =>
            {
                _showAlternativeExecutables = !_showAlternativeExecutables;
                ShowGameDetails();
            };
            exeActions.Children.Add(toggle);
        }
        var browse = Button("BROWSE EXE");
        browse.Click += async (_, _) =>
        {
            var selected = await PickFileAsync("Select Windows game executable",
                new FilePickerFileType("Windows executable") { Patterns = new[] { "*.exe" } });
            if (selected is not null) await ConfirmExecutableAsync(selected);
        };
        exeActions.Children.Add(browse);
        var rescan = Button("RESCAN");
        rescan.Click += async (_, _) => await FindExecutablesAsync(game);
        exeActions.Children.Add(rescan);
        detail.Children.Add(exeActions);

        if (_showAlternativeExecutables)
        {
            var entries = new StackPanel { Spacing = 7 };
            foreach (var candidate in _exeCandidates)
            {
                var choice = candidate;
                var relative = Path.GetRelativePath(game.Folder, choice.Path);
                var select = Button((choice.Suspicious ? "⚠  " :
                    choice.Recommended ? "★  " : "") + relative +
                    (choice.Path == _exe ? "  ·  SELECTED" : ""));
                select.Click += async (_, _) =>
                {
                    _showAlternativeExecutables = false;
                    await ConfirmExecutableAsync(choice.Path);
                };
                entries.Children.Add(select);
            }
            detail.Children.Add(Panel(entries, new Thickness(12)));
        }
        _content.Children.Add(Panel(detail));

        if (HasInstallRecord())
        {
            var recordPanel = new StackPanel { Spacing = 10 };
            recordPanel.Children.Add(Text("RECORDED INSTALLATION", 12, AccentBrush, FontWeight.Bold));
            var trackedFiles = new List<string>();
            try
            {
                var stateFile = Path.Combine(Path.GetDirectoryName(_exe!)!,
                    ".amdnr-linux-install.json");
                using var record = JsonDocument.Parse(File.ReadAllText(stateFile));
                var state = record.RootElement;
                if (state.TryGetProperty("alias", out var alias))
                    recordPanel.Children.Add(Text("Proxy DLL: " + alias.GetString(), 14));
                if (state.TryGetProperty("files", out var files) &&
                    files.ValueKind == JsonValueKind.Array)
                {
                    recordPanel.Children.Add(Text($"Tracked files: {files.GetArrayLength()}", 14));
                    foreach (var file in files.EnumerateArray())
                    {
                        if (file.ValueKind == JsonValueKind.Object &&
                            file.TryGetProperty("path", out var name) &&
                            name.ValueKind == JsonValueKind.String &&
                            name.GetString() is { } path)
                            trackedFiles.Add(path);
                    }
                }
            }
            catch (Exception ex) when (ex is IOException or JsonException or UnauthorizedAccessException)
            {
                recordPanel.Children.Add(Text("Could not read installation record: " + ex.Message,
                    12, MutedBrush));
            }

            // Do not fill the whole game page with dozens of installed filenames.
            // Expand on demand, with an independent capped file-list viewport.
            var controls = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 10 };
            var fileList = new StackPanel { Spacing = 6 };
            var fileScroller = new ScrollViewer
            {
                Content = fileList,
                MaxHeight = 240,
                VerticalScrollBarVisibility = ScrollBarVisibility.Auto,
                HorizontalScrollBarVisibility = ScrollBarVisibility.Disabled,
                IsVisible = false,
            };
            if (trackedFiles.Count > 0)
            {
                var showFiles = Button($"SHOW TRACKED FILES ({trackedFiles.Count})");
                showFiles.Click += (_, _) =>
                {
                    fileScroller.IsVisible = !fileScroller.IsVisible;
                    showFiles.Content = fileScroller.IsVisible
                        ? "HIDE TRACKED FILES" : $"SHOW TRACKED FILES ({trackedFiles.Count})";
                    if (fileScroller.IsVisible && fileList.Children.Count == 0)
                    {
                        foreach (var name in trackedFiles)
                            fileList.Children.Add(Text("•  " + name, 12, MutedBrush));
                    }
                };
                controls.Children.Add(showFiles);
            }
            var runDoctor = Button("CHECK FILE INTEGRITY");
            runDoctor.Click += (_, _) => ShowDoctor();
            controls.Children.Add(runDoctor);
            recordPanel.Children.Add(controls);
            recordPanel.Children.Add(fileScroller);
            _content.Children.Add(Panel(recordPanel));
        }
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
        _exeBox.TextChanged += (_, _) =>
        {
            _exe = _exeBox.Text;
            RefreshInstallStatus();
        };
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

        var releaseSection = new StackPanel { Spacing = 11 };
        releaseSection.Children.Add(Text("UPSTREAM AMDNR BUILDS", 12, AccentBrush, FontWeight.Bold));
        releaseSection.Children.Add(Text("Browse published AMDNR packages. Downloaded ZIPs are verified against " +
            "upstream SHA256SUMS.txt before use. Downloads do not install anything.", 13, MutedBrush));

        var releases = new ComboBox
        {
            MinWidth = 350,
            MaxWidth = 720,
            PlaceholderText = "Load upstream builds to select a release",
            HorizontalAlignment = HorizontalAlignment.Stretch,
        };
        releaseSection.Children.Add(releases);
        var releaseActions = new StackPanel
        {
            Orientation = Orientation.Horizontal, Spacing = 12,
        };
        var loadReleases = Button("LOAD BUILDS");
        var download = Button("DOWNLOAD SELECTED ZIP", true);
        download.IsEnabled = false;
        loadReleases.Click += async (_, _) =>
        {
            if (_busy || _backend is null) return;
            _busy = true;
            loadReleases.IsEnabled = false;
            _status.Text = "Loading upstream AMDNR releases…";
            try
            {
                var entries = await _backend.ReleasesAsync();
                releases.ItemsSource = entries;
                releases.SelectedIndex = entries.Count > 0 ? 0 : -1;
                download.IsEnabled = entries.Count > 0;
                _status.Text = entries.Count > 0
                    ? $"Found {entries.Count} upstream AMDNR ZIP builds."
                    : "No verified upstream release ZIPs found.";
            }
            catch (Exception ex) { _status.Text = "Release lookup failed: " + ex.Message; }
            finally { _busy = false; loadReleases.IsEnabled = true; }
        };
        download.Click += async (_, _) =>
        {
            if (_busy || _backend is null || releases.SelectedItem is not ReleaseEntry chosen)
                return;
            _busy = true;
            download.IsEnabled = false;
            _status.Text = $"Downloading {chosen.Asset} ({chosen.Bytes / (1024 * 1024)} MiB); checking SHA-256…";
            try
            {
                var (exit, output) = await _backend.RunAsync(new[]
                {
                    "--download-release", chosen.Tag,
                    "--release-asset", chosen.Asset,
                });
                if (exit != 0) { _status.Text = "Download failed: " + output; return; }
                var path = output.Trim();
                if (!File.Exists(path)) { _status.Text = "Downloaded ZIP not found."; return; }
                _archive = path;
                if (_archiveBox is not null) _archiveBox.Text = path;
                _status.Text = "Verified ZIP ready. Review the game executable before installing.";
            }
            catch (Exception ex) { _status.Text = "Download failed: " + ex.Message; }
            finally { _busy = false; download.IsEnabled = true; }
        };
        releaseActions.Children.Add(loadReleases);
        releaseActions.Children.Add(download);
        releaseSection.Children.Add(releaseActions);
        _content.Children.Add(Panel(releaseSection));

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

        var installStatus = new StackPanel { Spacing = 6 };
        installStatus.Children.Add(Text("INSTALLATION STATUS", 11, AccentBrush, FontWeight.Bold));
        _installationStatus = Text("", 14, ForegroundBrush);
        installStatus.Children.Add(_installationStatus);
        section.Children.Add(Panel(installStatus, new Thickness(14)));
        var inspect = Button("VERIFY INSTALLED FILES");
        var inspection = new StackPanel { Spacing = 6 };
        inspect.Click += async (_, _) =>
        {
            if (_busy || _backend is null || string.IsNullOrWhiteSpace(_exe) || !File.Exists(_exe))
                return;
            _busy = true;
            inspect.IsEnabled = false;
            _status.Text = "Verifying installed files and backups…";
            try
            {
                var report = await _backend.InstallationAsync(_exe);
                inspection.Children.Clear();
                if (!report.Installed)
                    inspection.Children.Add(Text("No installation record exists for this executable.", 13, MutedBrush));
                else if (report.Status == "invalid_record")
                    inspection.Children.Add(Text("Installation record needs attention: " + report.Error,
                        13, ForegroundBrush));
                else
                {
                    inspection.Children.Add(Text(report.Status == "healthy"
                        ? "✓  Installation files verified" : "!  Installation needs attention",
                        15, report.Status == "healthy" ? AccentBrush : ForegroundBrush,
                        FontWeight.SemiBold));
                    inspection.Children.Add(Text(
                        $"Verified: {report.Verified}/{report.Files}  ·  Missing: {report.Missing}" +
                        $"  ·  Modified: {report.Modified}  ·  Missing backups: {report.BackupsMissing}",
                        13, MutedBrush));
                    inspection.Children.Add(Text("Proxy DLL: " + (report.Alias ?? "unknown"), 13));
                    inspection.Children.Add(Text("Installed from: " +
                        (report.SourceArchive ?? "Unknown (older install record)"), 13, MutedBrush));
                }
                _status.Text = "Installation inventory checked. No files were modified.";
            }
            catch (Exception ex) { _status.Text = "Installation verification failed: " + ex.Message; }
            finally { _busy = false; inspect.IsEnabled = true; RefreshInstallStatus(); }
        };
        section.Children.Add(inspect);
        section.Children.Add(inspection);
        RefreshInstallStatus();

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
        _installAction = installButton;
        installButton.Click += async (_, _) => await ExecuteAsync(true);
        var uninstallButton = Button("Uninstall / restore");
        _uninstallAction = uninstallButton;
        uninstallButton.Click += async (_, _) => await ExecuteAsync(false);
        buttons.Children.Add(installButton);
        buttons.Children.Add(uninstallButton);
        section.Children.Add(buttons);
        _content.Children.Add(Panel(section));
        RefreshInstallStatus();

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

    private void RefreshInstallStatus()
    {
        if (_installationStatus is null) return;
        bool validExe = !string.IsNullOrWhiteSpace(_exe) && File.Exists(_exe);
        bool hasRecord = validExe && HasInstallRecord();
        if (!validExe)
            _installationStatus.Text = "No game executable selected.";
        else if (!hasRecord)
            _installationStatus.Text = "Not installed by this Linux launcher for the selected executable.";
        else
        {
            try
            {
                var path = Path.Combine(Path.GetDirectoryName(_exe!)!,
                    ".amdnr-linux-install.json");
                using var record = JsonDocument.Parse(File.ReadAllText(path));
                var state = record.RootElement;
                if (!state.TryGetProperty("format", out var version) ||
                    version.GetInt32() != 1 ||
                    !state.TryGetProperty("files", out var files) ||
                    files.ValueKind != JsonValueKind.Array)
                    throw new JsonException("Invalid installation format");
                var alias = state.TryGetProperty("alias", out var dll)
                    ? dll.GetString() ?? "unknown" : "unknown";
                _installationStatus.Text = $"Installation recorded · {alias} · " +
                    $"{files.GetArrayLength()} tracked files. Use Doctor to verify integrity.";
            }
            catch (Exception ex) when (ex is IOException or JsonException or UnauthorizedAccessException or InvalidOperationException)
            {
                _installationStatus.Text = "Installation record found but cannot be read. " +
                    "Run Doctor before making changes.";
            }
        }
        if (_installAction is not null)
        {
            _installAction.IsEnabled = validExe && !hasRecord && !_busy;
            _installAction.Content = hasRecord ? "Already installed" : "Install AMDNR";
        }
        if (_uninstallAction is not null)
            _uninstallAction.IsEnabled = validExe && hasRecord && !_busy;
    }

    private async Task ExecuteAsync(bool install)
    {
        if (_busy) return;
        if (_backend is null)
        {
            _status.Text = "Linux backend not found; see Launcher/Avalonia/README.md";
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
            _status.Text = exit == 0
                ? (install ? "Installation completed. " : "Uninstall completed. ") + output
                : $"Operation returned {exit}: {output}";
        }
        catch (Exception ex) { _status.Text = $"Operation failed: {ex.Message}"; }
        finally { _busy = false; RefreshInstallStatus(); }
    }

    private void ShowDoctor()
    {
        Clear("Doctor");
        _content.Children.Add(Text("Doctor", 30, ForegroundBrush, FontWeight.Bold));
        _content.Children.Add(Text("Environment and installation checks for Steam/Proton.",
            14, MutedBrush));
        var checks = new StackPanel { Spacing = 14 };
        var lines = new List<(string Name, bool Okay, bool Pending)>
        {
            ("Linux desktop", OperatingSystem.IsLinux(), false),
            ("Python 3 backend", _backend is not null, false),
            ("Steam library discovered", _games.Count > 0, false),
            ("Selected game executable", _exe is not null && File.Exists(_exe),
                string.IsNullOrWhiteSpace(_exe)),
            ("Selected release archive", _archive is not null && File.Exists(_archive),
                string.IsNullOrWhiteSpace(_archive)),
        };
        foreach (var (name, okay, pending) in lines)
        {
            var row = new Grid { ColumnDefinitions = new ColumnDefinitions("Auto,*"), ColumnSpacing = 12 };
            row.Children.Add(Text(okay ? "✓" : pending ? "○" : "!", 18,
                okay ? AccentBrush : MutedBrush));
            var info = Text(name + (pending ? "  ·  Not selected" : ""), 15);
            Grid.SetColumn(info, 1);
            row.Children.Add(info);
            checks.Children.Add(row);
        }
        _content.Children.Add(Panel(checks));

        var runChecks = Button("RUN INSTALLATION DIAGNOSTICS", true);
        var results = new StackPanel { Spacing = 12 };
        runChecks.Click += async (_, _) =>
        {
            if (_backend is null || _busy) return;
            _busy = true;
            runChecks.IsEnabled = false;
            _status.Text = "Checking Steam and installed files…";
            try
            {
                var arguments = new List<string> { "--doctor-json" };
                if (!string.IsNullOrWhiteSpace(_exe))
                {
                    arguments.Add("--exe");
                    arguments.Add(_exe);
                }
                if (!string.IsNullOrWhiteSpace(_archive))
                {
                    arguments.Add("--archive");
                    arguments.Add(_archive);
                }
                var (exit, output) = await _backend.RunAsync(arguments);
                if (exit != 0) throw new InvalidOperationException(output);
                using var report = JsonDocument.Parse(output);
                results.Children.Clear();
                foreach (var check in report.RootElement.GetProperty("checks").EnumerateArray())
                {
                    var name = check.GetProperty("name").GetString() ?? "Check";
                    var detail = check.GetProperty("detail").GetString() ?? "";
                    var okay = check.GetProperty("ok").GetBoolean();
                    var pending = check.TryGetProperty("status", out var state)
                        && state.GetString() == "not_selected";
                    var line = new StackPanel { Spacing = 3 };
                    line.Children.Add(Text((okay ? "✓  " : pending ? "○  " : "!  ") +
                        name + (pending ? " · Not selected" : ""), 15,
                        okay ? AccentBrush : pending ? MutedBrush : ForegroundBrush,
                        FontWeight.SemiBold));
                    line.Children.Add(Text(detail, 12, MutedBrush));
                    results.Children.Add(line);
                }
                _status.Text = "Read-only diagnostics completed.";
            }
            catch (Exception ex) { _status.Text = "Doctor failed: " + ex.Message; }
            finally { _busy = false; runChecks.IsEnabled = true; }
        };
        _content.Children.Add(runChecks);
        _content.Children.Add(Panel(results));
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
