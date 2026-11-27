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
using System.Diagnostics;
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
    private IReadOnlyList<string> _nativeExecutables = Array.Empty<string>();
    private string _exeScanReason = "";
    private string? _steamPreferredExe;
    private string? _steamLaunchReason;
    private IReadOnlyList<string> _steamMissingWindows = Array.Empty<string>();
    private bool _exeScanPartial;
    private bool _showAlternativeExecutables;
    private readonly Dictionary<string, Button> _navigation = new();
    private Backend? _backend;
    private List<GameEntry> _games = new();
    private string? _selectedFolder;
    private string? _exe;
    private string? _archive;
    private string _alias = "dxgi.dll";
    private LauncherSettings? _launcherSettings;
    private bool _launcherSettingsLoaded;
    private TextBox? _exeBox;
    private TextBox? _archiveBox;
    private TextBlock? _installationStatus;
    private Button? _installAction;
    private Button? _uninstallAction;
    private ComboBox? _aliasBox;
    private TextBlock? _installOverridePreview;
    private SteamUserOptions? _steamUserOptions;
    private bool _busy;
    private string _libraryQuery = "";
    private bool _missingArtOnly;
    private StackPanel? _libraryResults;
    private TextBox? _librarySearch;
    private readonly Dictionary<string, LibraryAuditEntry> _libraryAudit = new(StringComparer.Ordinal);
    private readonly Dictionary<string, string> _indexedExecutables = new(StringComparer.Ordinal);
    private string _auditFilter = "All games";
    private bool _auditSnapshotLoaded;

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
        Opened += async (_, _) =>
        {
            await LoadLauncherSettingsAsync();
            await RefreshGamesAsync();
        };
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
        AddNav(stack, "Installed", ShowInstalledGames);
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

    private async void ShowInstalledGames()
    {
        Clear("Installed");
        _content.Children.Add(Text("Installed Games", 30, ForegroundBrush, FontWeight.Bold));
        _content.Children.Add(Text("Manage AMDNR installations from your saved game library. " +
            "This view reads only recorded installation metadata; it never scans or hashes game files.",
            14, MutedBrush));

        var results = new StackPanel { Spacing = 12 };
        results.Children.Add(Text("Checking saved installation records…", 14, MutedBrush));
        _content.Children.Add(results);
        if (_backend is null)
        {
            results.Children.Clear();
            results.Children.Add(Text("Linux backend is unavailable.", 14, MutedBrush));
            return;
        }
        try
        {
            var installed = await _backend.InstalledGamesAsync();
            if (_currentSection != "Installed") return;
            results.Children.Clear();
            var valid = installed.Count(item => item.Status == "recorded");
            var invalid = installed.Count - valid;
            results.Children.Add(Text(
                $"{valid} recorded installation{(valid == 1 ? "" : "s")}" +
                (invalid > 0 ? $"  ·  {invalid} record{(invalid == 1 ? "" : "s")} need attention" : ""),
                15, AccentBrush, FontWeight.SemiBold));
            if (installed.Count == 0)
            {
                var empty = new StackPanel { Spacing = 10 };
                empty.Children.Add(Text("No indexed AMDNR installations found",
                    19, ForegroundBrush, FontWeight.SemiBold));
                empty.Children.Add(Text("Install AMDNR into a game with a remembered Windows " +
                    "executable to see its record here. Previously installed games without " +
                    "a selected executable may need to be opened or rescanned once.",
                    13, MutedBrush));
                var library = Button("OPEN LIBRARY", true);
                library.Click += (_, _) => ShowLibrary();
                empty.Children.Add(library);
                results.Children.Add(Panel(empty));
                return;
            }
            foreach (var item in installed)
            {
                var entry = item;
                var details = new StackPanel { Spacing = 8 };
                details.Children.Add(Text(entry.Name, 20, ForegroundBrush, FontWeight.SemiBold));
                details.Children.Add(Text(entry.Status == "recorded"
                    ? "✓  Installation record found · file integrity not verified"
                    : "!  Installation record is invalid or unreadable",
                    13, entry.Status == "recorded" ? AccentBrush : MutedBrush,
                    FontWeight.SemiBold));
                details.Children.Add(Text("Game executable: " +
                    Path.GetFileName(entry.Executable), 13, ForegroundBrush));
                if (entry.Status == "recorded")
                {
                    details.Children.Add(Text("Proxy DLL: " + entry.Alias +
                        $"  ·  Tracked files: {entry.TrackedFiles}", 13, MutedBrush));
                    if (!string.IsNullOrEmpty(entry.SourceArchive))
                        details.Children.Add(Text("Source: " +
                            Path.GetFileName(entry.SourceArchive), 12, MutedBrush));
                }
                var actions = new WrapPanel { ItemSpacing = 10, LineSpacing = 8 };
                var manage = Button("OPEN GAME", true);
                var game = _games.FirstOrDefault(g =>
                    string.Equals(Path.GetFullPath(g.Folder),
                        Path.GetFullPath(entry.Folder), StringComparison.Ordinal));
                manage.IsEnabled = game is not null;
                manage.Click += (_, _) =>
                {
                    if (game is not null) SelectGame(game);
                };
                actions.Children.Add(manage);
                var folder = Button("OPEN FOLDER");
                folder.Click += (_, _) => OpenGameFolder(entry.Folder);
                actions.Children.Add(folder);
                details.Children.Add(actions);
                results.Children.Add(Panel(details));
            }
            results.Children.Add(Text("This is an inventory of installation records, not a " +
                "compatibility or file-integrity verdict. Open a game and run Doctor / " +
                "Verify Installed Files to check its installation.", 12, MutedBrush));
        }
        catch (Exception ex)
        {
            if (_currentSection != "Installed") return;
            results.Children.Clear();
            results.Children.Add(Text("Could not read installed games: " + ex.Message,
                13, MutedBrush));
        }
    }

    private void ShowLibrary()
    {
        Clear("Library");
        _content.Children.Add(Text("Your games", 30, ForegroundBrush, FontWeight.Bold));
        _content.Children.Add(Text("Detected Steam installations and saved custom games.",
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
        manual.Click += (_, _) => ShowAddCustomGame();
        Grid.SetColumn(manual, 2);
        toolbar.Children.Add(manual);
        _content.Children.Add(toolbar);

        var auditBar = new StackPanel { Spacing = 10 };
        auditBar.Children.Add(Text("GAME READINESS  /  LIBRARY AUDIT", 12, AccentBrush, FontWeight.Bold));
        auditBar.Children.Add(Text("Results are saved across restarts. Refresh updates the game list without reanalyzing; " +
            "only Analyze / Rescan Library rebuilds this snapshot. AMDNR records do not verify file integrity.",
            12, MutedBrush));
        var auditControls = new WrapPanel { Orientation = Orientation.Horizontal, ItemSpacing = 10,
            LineSpacing = 8 };
        var auditButton = Button(_libraryAudit.Count > 0 ? "RESCAN LIBRARY" : "ANALYZE LIBRARY", true);
        auditButton.Click += async (_, _) => await AuditLibraryAsync(auditButton);
        auditControls.Children.Add(auditButton);
        var filters = new ComboBox
        {
            ItemsSource = new[] { "All games", "Windows ready", "Native Linux",
                "Needs attention", "AMDNR recorded" },
            SelectedItem = _auditFilter,
            MinWidth = 200,
            HorizontalAlignment = HorizontalAlignment.Left,
        };
        filters.SelectionChanged += (_, _) =>
        {
            _auditFilter = filters.SelectedItem?.ToString() ?? "All games";
            RenderLibraryResults();
        };
        auditControls.Children.Add(filters);
        auditBar.Children.Add(auditControls);
        _content.Children.Add(Panel(auditBar, new Thickness(14)));

        _libraryResults = new StackPanel { Spacing = 12 };
        _content.Children.Add(_libraryResults);
        RenderLibraryResults();
    }

    private void ShowAddCustomGame()
    {
        Clear("Library");
        _content.Children.Add(Text("Add custom game", 27, ForegroundBrush, FontWeight.Bold));
        var form = new StackPanel { Spacing = 12 };
        form.Children.Add(Text("DISPLAY NAME (OPTIONAL)", 11, AccentBrush, FontWeight.Bold));
        var nameBox = new TextBox { Watermark = "Defaults to folder name" };
        form.Children.Add(nameBox);
        form.Children.Add(Text("GAME INSTALLATION FOLDER", 11, AccentBrush, FontWeight.Bold));
        var folderBox = new TextBox { Watermark = "/path/to/your/game" };
        form.Children.Add(folderBox);
        var browse = Button("BROWSE GAME FOLDER");
        browse.Click += async (_, _) =>
        {
            var folders = await StorageProvider.OpenFolderPickerAsync(new FolderPickerOpenOptions
            {
                Title = "Choose custom game installation folder", AllowMultiple = false,
            });
            var chosen = folders.FirstOrDefault()?.TryGetLocalPath();
            if (chosen is not null)
            {
                folderBox.Text = chosen;
                if (string.IsNullOrWhiteSpace(nameBox.Text))
                    nameBox.Text = Path.GetFileName(chosen.TrimEnd(Path.DirectorySeparatorChar));
            }
        };
        form.Children.Add(browse);
        form.Children.Add(Text("OPTIONAL WINDOWS EXECUTABLE", 11, AccentBrush, FontWeight.Bold));
        var exeBox = new TextBox { Watermark = "Select a .exe if known; otherwise leave blank" };
        form.Children.Add(exeBox);
        var browseExe = Button("BROWSE EXE");
        browseExe.Click += async (_, _) =>
        {
            var picked = await PickFileAsync("Choose game executable",
                new FilePickerFileType("Windows executable") { Patterns = new[] { "*.exe" } });
            if (picked is not null)
            {
                exeBox.Text = picked;
                if (string.IsNullOrWhiteSpace(folderBox.Text))
                    folderBox.Text = Path.GetDirectoryName(picked);
                if (string.IsNullOrWhiteSpace(nameBox.Text))
                    nameBox.Text = Path.GetFileNameWithoutExtension(picked);
            }
        };
        form.Children.Add(browseExe);
        form.Children.Add(Text("The launcher will scan this folder for Windows executables. " +
            "This does not modify the selected game.", 12, MutedBrush));
        var actions = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 10 };
        var save = Button("SAVE TO LIBRARY", true);
        save.Click += async (_, _) =>
        {
            if (_backend is null || _busy) return;
            var folder = folderBox.Text?.Trim() ?? "";
            if (!Directory.Exists(folder))
            {
                _status.Text = "Choose an existing game folder first.";
                return;
            }
            var chosenExe = exeBox.Text?.Trim() ?? "";
            if (chosenExe.Length > 0 && (!File.Exists(chosenExe) ||
                !chosenExe.EndsWith(".exe", StringComparison.OrdinalIgnoreCase) ||
                !Path.GetFullPath(chosenExe).StartsWith(
                    Path.GetFullPath(folder).TrimEnd(Path.DirectorySeparatorChar) +
                    Path.DirectorySeparatorChar, StringComparison.Ordinal)))
            {
                _status.Text = "Choose a Windows .exe inside the selected game folder.";
                return;
            }
            if (_games.Any(g => string.Equals(Path.GetFullPath(g.Folder),
                Path.GetFullPath(folder), StringComparison.Ordinal)))
            {
                _status.Text = "This folder is already in your Library.";
                return;
            }
            _busy = true;
            save.IsEnabled = false;
            try
            {
                await _backend.AddCustomGameAsync(folder, nameBox.Text ?? "");
                string preferenceWarning = "";
                if (chosenExe.Length > 0)
                {
                    try { await _backend.RememberExecutableAsync(folder, chosenExe); }
                    catch (Exception ex) { preferenceWarning = " Executable preference was not saved: " + ex.Message; }
                }
                await ReloadGamesAsync();
                ShowLibrary();
                _status.Text = "Custom game saved to your library." + preferenceWarning;
            }
            catch (Exception ex) { _status.Text = "Could not add game: " + ex.Message; }
            finally { _busy = false; save.IsEnabled = true; }
        };
        actions.Children.Add(save);
        var cancel = Button("CANCEL");
        cancel.Click += (_, _) => ShowLibrary();
        actions.Children.Add(cancel);
        form.Children.Add(actions);
        _content.Children.Add(Panel(form));
    }

    private void ShowEditCustomGame(GameEntry game)
    {
        if (!game.Custom) return;
        Clear("Library");
        _content.Children.Add(Text("Edit custom game", 27, ForegroundBrush, FontWeight.Bold));
        var form = new StackPanel { Spacing = 12 };
        form.Children.Add(Text("DISPLAY NAME", 11, AccentBrush, FontWeight.Bold));
        var nameBox = new TextBox { Text = game.Name };
        form.Children.Add(nameBox);
        form.Children.Add(Text("Installation folder: " + game.Folder, 13, MutedBrush));
        var save = Button("SAVE NAME", true);
        save.Click += async (_, _) =>
        {
            if (_backend is null || _busy) return;
            try
            {
                await _backend.RenameCustomGameAsync(game.Folder, nameBox.Text ?? "");
                await ReloadGamesAsync();
                _selectedGame = _games.FirstOrDefault(g => g.Custom && g.Folder == game.Folder);
                ShowLibrary();
                _status.Text = "Custom game renamed.";
            }
            catch (Exception ex) { _status.Text = "Rename failed: " + ex.Message; }
        };
        form.Children.Add(save);
        var remove = Button("REMOVE FROM LIBRARY");
        remove.Click += (_, _) =>
        {
            remove.IsEnabled = false;
            var confirm = Button("CONFIRM REMOVAL (GAME FILES UNTOUCHED)", true);
            confirm.Click += async (_, _) =>
            {
                if (_backend is null || _busy) return;
                _busy = true;
                try
                {
                    await _backend.RemoveCustomGameAsync(game.Folder);
                    _selectedGame = null;
                    _exe = null;
                    await ReloadGamesAsync();
                    ShowLibrary();
                    _status.Text = "Custom entry removed; no game files were changed.";
                }
                catch (Exception ex) { _status.Text = "Removal failed: " + ex.Message; }
                finally { _busy = false; }
            };
            form.Children.Add(confirm);
        };
        form.Children.Add(remove);
        var back = Button("BACK");
        back.Click += (_, _) => ShowGameDetails();
        form.Children.Add(back);
        _content.Children.Add(Panel(form));
    }

    private async Task AuditLibraryAsync(Button trigger)
    {
        if (_busy || _backend is null) return;
        _busy = true;
        trigger.IsEnabled = false;
        trigger.Content = "ANALYZING LIBRARY…";
        _status.Text = "Auditing installed game executables (read-only)…";
        try
        {
            var entries = await _backend.AuditLibraryAsync();
            _libraryAudit.Clear();
            foreach (var item in entries)
            {
                var folder = Path.GetFullPath(item.Folder);
                _libraryAudit[folder] = item;
                if (item.Executable is not null && File.Exists(item.Executable))
                    _indexedExecutables[folder] = item.Executable;
                else
                    _indexedExecutables.Remove(folder);
            }
            _status.Text = $"Analyzed {entries.Count} games · " +
                $"{entries.Count(e => e.Status == "windows_ready")} Windows ready · " +
                $"{entries.Count(e => e.Status == "native_linux")} native Linux · " +
                $"{entries.Count(e => e.InstalledRecord)} AMDNR records.";
            RenderLibraryResults();
            trigger.Content = "RESCAN LIBRARY";
        }
        catch (Exception ex)
        {
            _status.Text = "Library audit failed: " + ex.Message;
            trigger.Content = _libraryAudit.Count > 0 ? "RESCAN LIBRARY" : "ANALYZE LIBRARY";
        }
        finally { _busy = false; trigger.IsEnabled = true; }
    }

    private bool MatchesAuditFilter(GameEntry game)
    {
        if (_auditFilter == "All games") return true;
        if (!_libraryAudit.TryGetValue(Path.GetFullPath(game.Folder), out var entry))
            return false;
        return _auditFilter switch
        {
            "Windows ready" => entry.Status == "windows_ready",
            "Native Linux" => entry.Status == "native_linux",
            "AMDNR recorded" => entry.InstalledRecord,
            "Needs attention" => entry.Status is not ("windows_ready" or "native_linux"),
            _ => true,
        };
    }

    private void RenderLibraryResults()
    {
        if (_libraryResults is null) return;
        _libraryResults.Children.Clear();
        var filtered = _games.Where(game =>
            (!_missingArtOnly || (!game.Custom && string.IsNullOrEmpty(game.Artwork))) &&
            MatchesAuditFilter(game) &&
            (game.Name.Contains(_libraryQuery, StringComparison.OrdinalIgnoreCase) ||
             game.Folder.Contains(_libraryQuery, StringComparison.OrdinalIgnoreCase))).ToList();
        var missingCount = _games.Count(game => !game.Custom && string.IsNullOrEmpty(game.Artwork));
        var customCount = _games.Count(game => game.Custom);
        _libraryResults.Children.Add(Text(
            $"{filtered.Count} of {_games.Count} entries  •  {customCount} custom  •  {missingCount} Steam covers missing" +
            (_libraryAudit.Count == 0 ? "  •  readiness not scanned" :
                $"  •  {_libraryAudit.Values.Count(a => a.Status == "windows_ready")} Windows ready" +
                $"  •  {_libraryAudit.Values.Count(a => a.Status == "native_linux")} native Linux"),
            12, AccentBrush, FontWeight.SemiBold));

        if (filtered.Count == 0)
        {
            var empty = new StackPanel { Spacing = 12 };
            empty.Children.Add(Text(_games.Count == 0 ? "No Steam games detected" : "No matching games",
                20, ForegroundBrush, FontWeight.SemiBold));
            empty.Children.Add(Text(_games.Count == 0
                ? "Check Steam libraries or add a custom game."
                : _missingArtOnly ? "All visible games have covers. Choose SHOW ALL to return." :
                    _auditFilter != "All games" ?
                        "No games match this readiness filter. Choose All games or analyze the library." :
                        "Try searching for a shorter name or clear the search field.", 13, MutedBrush));
            var action = Button(_games.Count == 0 ? "Add a custom game" : "Clear search", true);
            action.Click += (_, _) =>
            {
                if (_games.Count == 0) ShowAddCustomGame();
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
        detail.Children.Add(Text(game.Custom ? "CUSTOM GAME  ·  LOCAL" : "STEAM  ·  GAME INSTALLATION", 11, MutedBrush, FontWeight.SemiBold));
        if (_libraryAudit.TryGetValue(Path.GetFullPath(game.Folder), out var audit))
        {
            var readiness = audit.Status switch
            {
                "windows_ready" => "✓  WINDOWS EXE READY" +
                    (audit.Source is null ? "" : $"  ·  {audit.Source.ToUpperInvariant()}"),
                "native_linux" => "●  NATIVE LINUX BUILD",
                "needs_selection" => "○  CHOOSE WINDOWS EXECUTABLE",
                "no_windows_exe" => "○  WINDOWS EXECUTABLE NOT FOUND",
                "missing_folder" => "!  INSTALLATION FOLDER UNAVAILABLE",
                "scan_incomplete" => "!  SCAN INCOMPLETE",
                _ => "!  EXECUTABLE NEEDS ATTENTION",
            };
            detail.Children.Add(Text(readiness +
                (audit.InstalledRecord ? "  ·  AMDNR RECORDED" : ""),
                11, audit.Status == "windows_ready" ? AccentBrush : MutedBrush,
                FontWeight.SemiBold));
        }
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
        var bottom = Text(game.Custom ? "CUSTOM  ·  COVER NOT AVAILABLE" : "STEAM  ·  COVER NOT AVAILABLE", 9, MutedBrush);
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

    private async Task ReadGameSteamOptionsAsync(GameEntry game)
    {
        if (_backend is null || game.Custom)
        {
            _steamUserOptions = null;
            return;
        }
        try
        {
            var alias = _exe is not null ? RecordedAlias(_exe) ?? _alias : _alias;
            var options = await _backend.SteamUserOptionsAsync(game.Folder, alias);
            if (_selectedGame?.Folder == game.Folder)
                _steamUserOptions = options;
        }
        catch (Exception)
        {
            if (_selectedGame?.Folder == game.Folder)
                _steamUserOptions = new SteamUserOptions("unavailable", null, null, null);
        }
    }

    private async void SelectGame(GameEntry game)
    {
        if (_busy) return;
        _selectedGame = game;
        _selectedFolder = game.Folder;
        _exe = null;
        _exeCandidates = Array.Empty<ExecutableEntry>();
        _nativeExecutables = Array.Empty<string>();
        _exeScanReason = "";
        _steamPreferredExe = null;
        _steamLaunchReason = null;
        _steamMissingWindows = Array.Empty<string>();
        _steamUserOptions = null;
        _exeScanPartial = false;
        _showAlternativeExecutables = false;
        if (_indexedExecutables.TryGetValue(Path.GetFullPath(game.Folder), out var cached) &&
            File.Exists(cached))
        {
            _exe = cached;
            await ReadGameSteamOptionsAsync(game);
            _status.Text = "Restored indexed executable: " + Path.GetFileName(cached) +
                " · Rescan for updated candidates.";
            ShowGameDetails();
            return;
        }
        // Native / no-EXE results from a completed audit do not require another
        // expensive binary crawl when opening the same game.
        if (_libraryAudit.TryGetValue(Path.GetFullPath(game.Folder), out var audit) &&
            audit.Status is "native_linux" or "no_windows_exe" or "scan_incomplete")
        {
            _exeScanReason = audit.Status == "native_linux"
                ? "native_linux_files" : audit.Status;
            await ReadGameSteamOptionsAsync(game);
            _status.Text = audit.Status == "native_linux"
                ? "Restored native Linux detection from saved audit · Rescan to update."
                : "Restored executable scan result from saved audit · Rescan to update.";
            ShowGameDetails();
            return;
        }
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
            var scan = await _backend.ScanExecutablesAsync(game.Folder);
            var results = scan.Candidates;
            // Do not navigate to a different game after an asynchronous scan.
            if (_selectedGame?.Folder != game.Folder) return;
            _exeCandidates = results;
            _nativeExecutables = scan.NativeFiles;
            _exeScanReason = scan.Reason;
            _steamPreferredExe = scan.SteamPreferred;
            _steamLaunchReason = scan.SteamReason;
            _steamMissingWindows = scan.SteamMissingWindows;
            _exeScanPartial = scan.Partial;
            var saved = await _backend.SavedExecutableAsync(game.Folder);
            if (_selectedGame?.Folder != game.Folder) return;
            var chosen = saved ?? results.FirstOrDefault(e => e.AutoSelect)?.Path;
            _exe = chosen;
            await ReadGameSteamOptionsAsync(game);
            if (chosen is not null && File.Exists(chosen))
            {
                _indexedExecutables[Path.GetFullPath(game.Folder)] = chosen;
                // The indexed choice is distinct from a manual preference: saving
                // automatic discovery must not override explicit manual selection.
                try { await _backend.IndexLibraryExecutableAsync(game.Folder, chosen); }
                catch (Exception) { /* Valid in-session selection still works. */ }
            }
            _status.Text = saved is not null
                ? "Restored saved executable: " + Path.GetFileName(saved)
                : chosen is not null
                    ? scan.SteamPreferred == chosen
                        ? (scan.SteamReason == "steam_unique_option"
                            ? "Selected Steam's sole installed Windows executable: "
                            : "Selected Steam's primary Windows executable: ") + Path.GetFileName(chosen)
                        : "Automatically selected likely game executable: " + Path.GetFileName(chosen)
                    : results.Count == 0
                        ? scan.Reason == "native_linux_files"
                            ? "Native Linux executables found; no Windows .exe detected."
                            : scan.Partial
                                ? "No Windows EXE found; some folders could not be scanned."
                                : "No Windows executable detected. Choose one manually."
                        : "Several possible executables found. Select the correct one.";
            ShowGameDetails();
        }
        catch (Exception ex)
        {
            _exeScanReason = "scan_error";
            _status.Text = "Executable scan failed: " + ex.Message;
            if (_selectedGame?.Folder == game.Folder) ShowGameDetails();
        }
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
            await ReadGameSteamOptionsAsync(game);
            _indexedExecutables[Path.GetFullPath(game.Folder)] = path;
            try { await _backend.IndexLibraryExecutableAsync(game.Folder, path); }
            catch (Exception) { /* Manual choice was already saved independently. */ }
            _status.Text = "Saved executable preference: " + Path.GetFileName(path);
            ShowGameDetails();
        }
        catch (Exception ex) { _status.Text = "Could not save executable choice: " + ex.Message; }
    }

    private bool HasInstallRecord()
        => !string.IsNullOrWhiteSpace(_exe) &&
           File.Exists(Path.Combine(Path.GetDirectoryName(_exe)!, ".amdnr-linux-install.json"));

    private static string? ProtonOverride(string alias)
    {
        if (alias.EndsWith(".asi", StringComparison.OrdinalIgnoreCase))
            return null;
        return $"WINEDLLOVERRIDES=\"{Path.GetFileNameWithoutExtension(alias).ToLowerInvariant()}=n,b\" %command%";
    }

    private static string? RecordedAlias(string executable)
    {
        try
        {
            var stateFile = Path.Combine(Path.GetDirectoryName(executable)!,
                ".amdnr-linux-install.json");
            if (!File.Exists(stateFile)) return null;
            using var record = JsonDocument.Parse(File.ReadAllText(stateFile));
            return record.RootElement.TryGetProperty("alias", out var value) &&
                value.ValueKind == JsonValueKind.String ? value.GetString() : null;
        }
        catch (Exception ex) when (ex is IOException or JsonException or UnauthorizedAccessException)
        {
            return null;
        }
    }

    private async Task CopyToClipboardAsync(string value, string success)
    {
        if (Clipboard is null)
        {
            _status.Text = "Clipboard not available on this desktop session.";
            return;
        }
        try
        {
            await Clipboard.SetTextAsync(value);
            _status.Text = success;
        }
        catch (Exception ex)
        {
            _status.Text = "Clipboard unavailable: " + ex.Message;
        }
    }

    private void OpenGameFolder(string folder)
    {
        if (!Directory.Exists(folder))
        {
            _status.Text = "Game folder is unavailable.";
            return;
        }
        try
        {
            var process = new ProcessStartInfo("xdg-open")
            {
                UseShellExecute = false,
                CreateNoWindow = true,
            };
            process.ArgumentList.Add(folder);
            Process.Start(process)?.Dispose();
        }
        catch (Exception ex)
        {
            _status.Text = "Could not open game folder: " + ex.Message;
        }
    }

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
        var nativeOnly = _exeScanReason == "native_linux_files" && _exe is null;
        summary.Children.Add(Text(game.Custom ? "CUSTOM GAME  /  LOCAL" :
            nativeOnly ? "STEAM  /  NATIVE LINUX" : "STEAM  /  PROTON",
            12, AccentBrush, FontWeight.SemiBold));
        summary.Children.Add(Text(game.Name, 31, ForegroundBrush, FontWeight.Bold));
        bool installed = HasInstallRecord();
        summary.Children.Add(Text(installed ? "●  AMDNR installation recorded" :
            nativeOnly ? "●  Native Linux build installed · no Windows DLL target" :
            _exe is null ? "○  No Windows executable selected" :
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
        if (_exe is not null && File.Exists(_exe))
        {
            var configure = Button("CONFIGURE AMDNR");
            configure.Click += (_, _) => ShowGameConfiguration();
            summary.Children.Add(configure);
            var extensions = Button("MANAGE EXTENSIONS");
            extensions.Click += (_, _) => ShowExtensions();
            summary.Children.Add(extensions);
        }
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
        if (game.Custom)
        {
            var edit = Button("EDIT / REMOVE CUSTOM GAME");
            edit.Click += (_, _) => ShowEditCustomGame(game);
            summary.Children.Add(edit);
        }
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
            selected.Children.Add(Text(_steamPreferredExe == chosen
                ? "✓  Steam launch configuration · Windows executable"
                : "✓  Selected game executable · change anytime", 15,
                AccentBrush, FontWeight.SemiBold));
            selected.Children.Add(Text(Path.GetFileName(chosen), 20,
                ForegroundBrush, FontWeight.SemiBold));
            selected.Children.Add(Text(Path.GetRelativePath(game.Folder, chosen), 12, MutedBrush));
            detail.Children.Add(Panel(selected, new Thickness(14)));
        }
        else if (recommended is not null)
        {
            var suggestion = new StackPanel { Spacing = 9 };
            suggestion.Children.Add(Text(_steamPreferredExe == recommended.Path
                ? "★  Steam-declared Windows executable"
                : "★  Recommended executable · not yet confirmed",
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
            detail.Children.Add(Text(_exeScanReason.Length == 0 ? "Scanning game folder for Windows executables…"
                : _exeScanReason == "native_linux_files"
                    ? "This installation appears to be a native Linux game. No Windows .exe was found. " +
                      "AMDNR's Windows DLL cannot be installed into a native Linux executable."
                    : _exeScanReason == "scan_error"
                        ? "Executable scan failed. Check the header for details, then try Rescan."
                    : _exeScanPartial
                        ? "No Windows EXE found. The scan was incomplete; browse manually or check permissions."
                        : "No Windows executable detected. This may be a Linux-native build or a game " +
                          "with files located outside the scanned folder.", 14, MutedBrush));
            if (_nativeExecutables.Count > 0)
                detail.Children.Add(Text("Installed Linux executables: " +
                    string.Join(", ", _nativeExecutables.Take(3)), 13, ForegroundBrush));
            if (_steamMissingWindows.Count > 0)
                detail.Children.Add(Text("Steam lists a Windows launch target, but it is not installed: " +
                    string.Join(", ", _steamMissingWindows.Take(3)), 13, MutedBrush));
            else if (_steamLaunchReason == "metadata_missing" ||
                     _steamLaunchReason == "cache_unavailable")
                detail.Children.Add(Text("Steam launch metadata unavailable; filesystem scan used.",
                    12, MutedBrush));
        }

        if (!nativeOnly)
            detail.Children.Add(Text("Likely Windows game executables are selected automatically. " +
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

        var setup = new StackPanel { Spacing = 11 };
        setup.Children.Add(Text("GAME SETUP  /  QUICK ACTIONS", 12, AccentBrush, FontWeight.Bold));
        var selectedExe = !string.IsNullOrWhiteSpace(_exe) && File.Exists(_exe);
        var savedAlias = selectedExe ? RecordedAlias(_exe!) : null;
        var effectiveAlias = savedAlias ?? _alias;
        setup.Children.Add(Text(selectedExe
            ? "✓  Windows executable ready: " + Path.GetFileName(_exe!)
            : nativeOnly ? "○  Native Linux build detected; Windows DLL setup unavailable."
            : "○  Select a Windows game executable to continue.", 13,
            selectedExe ? ForegroundBrush : MutedBrush));
        setup.Children.Add(Text(HasInstallRecord()
            ? "✓  AMDNR installation recorded (integrity not yet verified)."
            : "○  AMDNR installation not recorded for this executable.", 13, MutedBrush));
        if (selectedExe)
        {
            var steamOptions = _steamUserOptions;
            var command = game.Custom ? ProtonOverride(effectiveAlias) :
                steamOptions?.Preview;
            setup.Children.Add(Text("STEAM / PROTON LAUNCH OPTIONS", 11, MutedBrush,
                FontWeight.Bold));
            if (game.Custom)
                setup.Children.Add(Text("Custom game: Steam launch options cannot be read automatically.",
                    12, MutedBrush));
            else if (steamOptions?.Status == "multiple_profiles")
                setup.Children.Add(Text("Multiple Steam profiles have different launch options. " +
                    "Select the active account's options in Steam; automatic merging is disabled.",
                    13, MutedBrush));
            else if (steamOptions?.Status == "unavailable" ||
                     steamOptions?.Status == "manifest_missing" ||
                     steamOptions?.Status == "not_steam_install")
                setup.Children.Add(Text("Steam launch options could not be read. " +
                    "Check Steam → Properties → General before setting an override.",
                    13, MutedBrush));
            else if (steamOptions?.Status == "found")
                setup.Children.Add(Text("Existing Steam options: " + steamOptions.Existing,
                    12, MutedBrush));
            else if (steamOptions?.Status == "empty")
                setup.Children.Add(Text("Steam has no existing launch options for this game.",
                    12, MutedBrush));
            else
                setup.Children.Add(Text("Reading Steam launch options…", 12, MutedBrush));
            if (command is not null)
            {
                setup.Children.Add(Text("FINAL PREVIEW · COPY INTO STEAM", 11,
                    AccentBrush, FontWeight.Bold));
                setup.Children.Add(Text(command, 14, ForegroundBrush, FontWeight.SemiBold));
            }
            else if (steamOptions?.ComposeStatus == "complex_options")
                setup.Children.Add(Text("Existing override is too complex to merge safely. " +
                    "Review it manually in Steam; the launcher will not overwrite it.",
                    13, MutedBrush));
            else if (effectiveAlias.EndsWith(".asi", StringComparison.OrdinalIgnoreCase))
                setup.Children.Add(Text("ASI plugins require a compatible ASI loader; " +
                    "no WINEDLLOVERRIDES entry.", 13, MutedBrush));
            setup.Children.Add(Text(savedAlias is not null
                ? "Override uses the installed proxy: " + savedAlias
                : "Preview uses the proxy selected on the Install page: " + effectiveAlias,
                12, MutedBrush));
            var tools = new WrapPanel { ItemSpacing = 10, LineSpacing = 8 };
            if (command is not null)
            {
                var copy = Button("COPY FINAL OPTIONS", true);
                copy.Click += async (_, _) => await CopyToClipboardAsync(command,
                    "Steam launch options copied.");
                tools.Children.Add(copy);
            }
            var copyExe = Button("COPY EXE PATH");
            copyExe.Click += async (_, _) => await CopyToClipboardAsync(_exe!,
                "Game executable path copied.");
            tools.Children.Add(copyExe);
            var open = Button("OPEN GAME FOLDER");
            open.Click += (_, _) => OpenGameFolder(game.Folder);
            tools.Children.Add(open);
            setup.Children.Add(tools);
        }
        else
        {
            var open = Button("OPEN GAME FOLDER");
            open.Click += (_, _) => OpenGameFolder(game.Folder);
            setup.Children.Add(open);
        }
        setup.Children.Add(Text("Set the options in Steam → Properties → General → Launch Options. " +
            "Compatibility depends on the game, Proton, and anti-cheat restrictions.",
            12, MutedBrush));
        _content.Children.Add(Panel(setup));

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
                var visible = _launcherSettings?.ShowPrereleases == true
                    ? entries : entries.Where(e => !e.Prerelease).ToList();
                releases.ItemsSource = visible;
                releases.SelectedIndex = visible.Count > 0 ? 0 : -1;
                download.IsEnabled = visible.Count > 0;
                _status.Text = visible.Count > 0
                    ? $"Found {visible.Count} upstream AMDNR ZIP builds."
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
        _aliasBox.SelectionChanged += (_, _) =>
        {
            _alias = _aliasBox.SelectedItem?.ToString() ?? "dxgi.dll";
            if (_installOverridePreview is not null)
                _installOverridePreview.Text = ProtonOverride(_alias) ??
                    "ASI plugins require a compatible ASI loader.";
        };
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
        _installOverridePreview = Text(ProtonOverride(_alias) ??
            "ASI plugins require a compatible ASI loader.", 14, AccentBrush);
        help.Children.Add(_installOverridePreview);
        var copyOverride = Button("Copy launch options");
        copyOverride.Click += async (_, _) =>
        {
            var value = ProtonOverride(_alias);
            if (value is null)
            {
                _status.Text = "ASI plugins require a compatible loader; no DLL override to copy.";
                return;
            }
            await CopyToClipboardAsync(value, "Steam launch options copied to clipboard.");
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

    private async Task LoadLauncherSettingsAsync()
    {
        if (_backend is null || _launcherSettingsLoaded) return;
        try
        {
            _launcherSettings = await _backend.SettingsAsync();
            _alias = _launcherSettings.DefaultAlias;
            _launcherSettingsLoaded = true;
        }
        catch (Exception ex) { _status.Text = "Launcher preferences unavailable: " + ex.Message; }
    }

    private async void ShowExtensions()
    {
        Clear("Library");
        _breadcrumb.Text = "AMDNR  /  Extensions";
        _content.Children.Add(Text("AMDNR Extensions", 30, ForegroundBrush, FontWeight.Bold));
        var back = Button("←  BACK TO GAME");
        back.Click += (_, _) => ShowGameDetails();
        _content.Children.Add(back);
        var selected = _exe;
        if (_backend is null || string.IsNullOrEmpty(selected) || !File.Exists(selected))
        {
            _content.Children.Add(Text("Select a Windows game executable first.",
                14, MutedBrush));
            return;
        }
        var body = new StackPanel { Spacing = 12 };
        _content.Children.Add(Panel(body));
        async Task Reload()
        {
            if (_backend is null) return;
            body.Children.Clear();
            body.Children.Add(Text("Reading plugin directory and loader settings…", 13, MutedBrush));
            try
            {
                var extensions = await _backend.ExtensionsAsync(selected);
                if (_exe != selected || _breadcrumb.Text != "AMDNR  /  Extensions") return;
                body.Children.Clear();
                body.Children.Add(Text("OPTISCALER PLUGINS", 12, AccentBrush, FontWeight.Bold));
                body.Children.Add(Text("Installed .asi and .dll plugins found in: " +
                    extensions.Folder, 12, MutedBrush));
                body.Children.Add(Text(extensions.Enabled is true
                    ? "ASI loader: enabled in OptiScaler.ini"
                    : extensions.Enabled is false
                        ? "ASI loader: disabled in OptiScaler.ini"
                        : "ASI loader: not explicitly configured", 14,
                    ForegroundBrush, FontWeight.SemiBold));
                var toggles = new WrapPanel { ItemSpacing = 10, LineSpacing = 8 };
                var enable = Button("ENABLE ASI LOADER");
                var disable = Button("DISABLE ASI LOADER");
                enable.IsEnabled = extensions.IniPresent;
                disable.IsEnabled = extensions.IniPresent;
                async Task Toggle(bool state)
                {
                    if (_busy || _backend is null) return;
                    _busy = true;
                    enable.IsEnabled = false;
                    disable.IsEnabled = false;
                    try
                    {
                        var snapshot = await _backend.ReadIniAsync(selected);
                        var saved = await _backend.SetExtensionLoaderAsync(
                            selected, snapshot.Sha256, state);
                        _status.Text = "ASI loader " + (state ? "enabled" : "disabled") +
                            ". INI backup: " + saved.Backup;
                    }
                    catch (Exception ex) { _status.Text = "Loader change refused: " + ex.Message; }
                    finally { _busy = false; await Reload(); }
                }
                enable.Click += async (_, _) => await Toggle(true);
                disable.Click += async (_, _) => await Toggle(false);
                toggles.Children.Add(enable);
                toggles.Children.Add(disable);
                body.Children.Add(toggles);
                body.Children.Add(Text("ASI loader changes are backed up. Importing a plugin " +
                    "does not automatically enable it; use a trusted plugin source.",
                    12, MutedBrush));
                var import = Button("IMPORT LOCAL .ASI", true);
                import.Click += async (_, _) =>
                {
                    if (_busy || _backend is null) return;
                    var file = await PickFileAsync("Import a trusted ASI plugin",
                        new FilePickerFileType("ASI plugins") { Patterns = new[] { "*.asi" } });
                    if (file is null) return;
                    _busy = true;
                    try
                    {
                        await _backend.ImportExtensionAsync(selected, file);
                        _status.Text = "Plugin imported: " + Path.GetFileName(file);
                    }
                    catch (Exception ex) { _status.Text = "Plugin import refused: " + ex.Message; }
                    finally { _busy = false; await Reload(); }
                };
                body.Children.Add(import);
                if (extensions.Plugins.Count == 0)
                    body.Children.Add(Text("No .asi or .dll plugins found in this game's " +
                        "plugins folder.", 13, MutedBrush));
                foreach (var plugin in extensions.Plugins)
                {
                    var item = plugin;
                    var detail = new StackPanel { Spacing = 7 };
                    detail.Children.Add(Text(item.Name, 15, ForegroundBrush,
                        FontWeight.SemiBold));
                    detail.Children.Add(Text(item.Managed
                        ? item.Modified
                            ? "Managed · modified since import · removal blocked"
                            : "Managed by Linux launcher · can safely remove"
                        : "Existing external plugin · not managed by this launcher",
                        12, MutedBrush));
                    if (item.Managed && !item.Modified)
                    {
                        var remove = Button("REMOVE MANAGED PLUGIN");
                        remove.Click += async (_, _) =>
                        {
                            if (_busy || _backend is null) return;
                            _busy = true;
                            remove.IsEnabled = false;
                            try
                            {
                                await _backend.RemoveExtensionAsync(selected, item.Name);
                                _status.Text = "Removed launcher-managed plugin: " + item.Name;
                            }
                            catch (Exception ex)
                            {
                                _status.Text = "Removal refused: " + ex.Message;
                            }
                            finally { _busy = false; await Reload(); }
                        };
                        detail.Children.Add(remove);
                    }
                    body.Children.Add(Panel(detail, new Thickness(12)));
                }
                body.Children.Add(Text("The launcher never removes pre-existing plugins, " +
                    "never replaces an extension on import, and refuses removal " +
                    "when an imported file has changed.", 12, MutedBrush));
            }
            catch (Exception ex)
            {
                body.Children.Clear();
                body.Children.Add(Text("Could not inspect extensions: " + ex.Message,
                    13, MutedBrush));
            }
        }
        await Reload();
    }

    private async void ShowGameConfiguration()
    {
        Clear("Library");
        _breadcrumb.Text = "AMDNR  /  Game Configuration";
        _content.Children.Add(Text("AMDNR Configuration", 30, ForegroundBrush, FontWeight.Bold));
        var back = Button("←  BACK TO GAME");
        back.Click += (_, _) => ShowGameDetails();
        _content.Children.Add(back);
        if (_backend is null || string.IsNullOrWhiteSpace(_exe) || !File.Exists(_exe))
        {
            _content.Children.Add(Text("Select a Windows executable first.", 14, MutedBrush));
            return;
        }
        var exe = _exe;
        var panel = new StackPanel { Spacing = 12 };
        panel.Children.Add(Text("Loading OptiScaler.ini…", 14, MutedBrush));
        _content.Children.Add(Panel(panel));
        try
        {
            var snapshot = await _backend.ReadIniAsync(exe);
            if (_selectedGame is null || _exe != exe) return;
            panel.Children.Clear();
            panel.Children.Add(Text("CONFIGURATION SECTIONS", 12, AccentBrush, FontWeight.Bold));
            var sections = snapshot.Sections
                .Where(s => s.Keys.Count > 0 || s.Name != "General (before sections)")
                .Select(s => s.Name + $" ({s.Keys.Count} settings)")
                .ToArray();
            panel.Children.Add(Text(sections.Length == 0 ? "No named settings found." :
                string.Join("  ·  ", sections), 12, MutedBrush));
            panel.Children.Add(Text("Edit the original INI text below. Comments and unknown " +
                "settings are preserved. Save creates an independent backup and refuses " +
                "to overwrite changes made by another application.", 13, MutedBrush));
            var editor = new TextBox
            {
                Text = snapshot.Text,
                AcceptsReturn = true,
                TextWrapping = TextWrapping.NoWrap,
                MinHeight = 340,
                MaxHeight = 560,
                FontFamily = new FontFamily("monospace"),
                Background = BackgroundBrush,
                Foreground = ForegroundBrush,
                HorizontalAlignment = HorizontalAlignment.Stretch,
                VerticalScrollBarVisibility = ScrollBarVisibility.Auto,
                HorizontalScrollBarVisibility = ScrollBarVisibility.Auto,
            };
            panel.Children.Add(editor);
            var outcome = Text("No changes saved.", 12, MutedBrush);
            var buttons = new WrapPanel { ItemSpacing = 10, LineSpacing = 8 };
            var save = Button("SAVE CONFIGURATION", true);
            save.Click += async (_, _) =>
            {
                if (_backend is null || _busy) return;
                _busy = true;
                save.IsEnabled = false;
                try
                {
                    var result = await _backend.SaveIniAsync(exe, snapshot.Sha256,
                        editor.Text ?? "");
                    _status.Text = result.Status == "saved"
                        ? "INI saved. Backup: " + result.Backup
                        : "INI unchanged.";
                    outcome.Text = _status.Text;
                    if (result.Status == "saved")
                    {
                        // A fresh checksum is required for subsequent edits.
                        var latest = await _backend.ReadIniAsync(exe);
                        snapshot = latest;
                    }
                }
                catch (Exception ex)
                {
                    outcome.Text = "Save refused: " + ex.Message;
                    _status.Text = outcome.Text;
                }
                finally { _busy = false; save.IsEnabled = true; }
            };
            buttons.Children.Add(save);
            var reload = Button("RELOAD FROM DISK");
            reload.Click += async (_, _) =>
            {
                if (_backend is null) return;
                try
                {
                    snapshot = await _backend.ReadIniAsync(exe);
                    editor.Text = snapshot.Text;
                    outcome.Text = "Reloaded configuration from disk.";
                }
                catch (Exception ex) { outcome.Text = "Reload failed: " + ex.Message; }
            };
            buttons.Children.Add(reload);
            panel.Children.Add(buttons);
            panel.Children.Add(outcome);
        }
        catch (Exception ex)
        {
            panel.Children.Clear();
            panel.Children.Add(Text("Unable to open configuration: " + ex.Message, 14, MutedBrush));
            panel.Children.Add(Text("The editor requires a regular UTF-8 OptiScaler.ini " +
                "beside the selected game executable.", 13, MutedBrush));
        }
    }

    private async void ShowSettings()
    {
        Clear("Settings");
        _content.Children.Add(Text("Settings", 30, ForegroundBrush, FontWeight.Bold));
        _content.Children.Add(Text("Persistent Linux launcher preferences. " +
            "Nothing here changes the original Windows launcher.", 14, MutedBrush));
        var panel = new StackPanel { Spacing = 12 };
        panel.Children.Add(Text("Loading preferences…", 14, MutedBrush));
        _content.Children.Add(Panel(panel));
        if (_backend is null) return;
        try
        {
            var config = await _backend.SettingsAsync();
            if (_currentSection != "Settings") return;
            _launcherSettings = config;
            _launcherSettingsLoaded = true;
            panel.Children.Clear();
            panel.Children.Add(Text("DEFAULT PROXY DLL", 12, AccentBrush, FontWeight.Bold));
            var aliases = new[] { "dxgi.dll", "version.dll", "winmm.dll", "winhttp.dll",
                "wininet.dll", "dbghelp.dll", "d3d12.dll", "OptiScaler.asi" };
            var choice = new ComboBox
            {
                ItemsSource = aliases,
                SelectedItem = config.DefaultAlias,
                Width = 235,
                HorizontalAlignment = HorizontalAlignment.Left,
            };
            panel.Children.Add(choice);
            panel.Children.Add(Text("RELEASE DOWNLOAD DIRECTORY", 12, AccentBrush, FontWeight.Bold));
            var download = new TextBox
            {
                Text = config.DownloadDirectory,
                Background = BackgroundBrush,
                Foreground = ForegroundBrush,
                HorizontalAlignment = HorizontalAlignment.Stretch,
            };
            panel.Children.Add(download);
            var prerelease = new CheckBox
            {
                Content = "Show prerelease builds in the release picker",
                IsChecked = config.ShowPrereleases,
                Foreground = ForegroundBrush,
            };
            panel.Children.Add(prerelease);
            panel.Children.Add(Text("Downloads remain manual and checksum-verified. " +
                "Settings are saved under your XDG configuration directory.", 12, MutedBrush));
            var save = Button("SAVE PREFERENCES", true);
            save.Click += async (_, _) =>
            {
                if (_busy || _backend is null) return;
                _busy = true;
                save.IsEnabled = false;
                try
                {
                    _launcherSettings = await _backend.SaveSettingsAsync(new LauncherSettings(
                        choice.SelectedItem?.ToString() ?? config.DefaultAlias,
                        download.Text ?? "",
                        prerelease.IsChecked == true));
                    _alias = _launcherSettings.DefaultAlias;
                    _status.Text = "Launcher preferences saved.";
                }
                catch (Exception ex) { _status.Text = "Preferences not saved: " + ex.Message; }
                finally { _busy = false; save.IsEnabled = true; }
            };
            panel.Children.Add(save);
        }
        catch (Exception ex)
        {
            panel.Children.Clear();
            panel.Children.Add(Text("Preferences unavailable: " + ex.Message, 13, MutedBrush));
        }
    }

    private async Task ReloadGamesAsync()
    {
        if (_backend is null) return;
        var current = await _backend.DifferentialGamesAsync();
        _games = current.Select(item => item.Game).ToList();
        _indexedExecutables.Clear();
        foreach (var item in current)
            if (item.Executable is not null)
                _indexedExecutables[Path.GetFullPath(item.Game.Folder)] = item.Executable;
        // New / removed Steam entries are reconciled via manifests; no binary
        // scan occurs here. Temporarily missing custom folders are retained.
        // Prune stale readiness rows even when the library changes via custom
        // game add/remove instead of the Refresh button.
        var currentFolders = new HashSet<string>(
            _games.Select(g => Path.GetFullPath(g.Folder)), StringComparer.Ordinal);
        foreach (var old in _libraryAudit.Keys.Where(p => !currentFolders.Contains(p)).ToList())
            _libraryAudit.Remove(old);
        // Preserve the saved audit snapshot across ordinary Library refreshes.
        // Newly discovered games simply show no readiness label until Rescan.
    }

    private async Task RefreshGamesAsync()
    {
        if (_busy || _backend is null) return;
        _busy = true;
        _status.Text = "Checking saved library against Steam manifests…";
        try
        {
            await ReloadGamesAsync();
            if (!_auditSnapshotLoaded)
            {
                _auditSnapshotLoaded = true;
                try
                {
                    var saved = await _backend.SavedLibraryAuditAsync();
                    foreach (var item in saved)
                        _libraryAudit[Path.GetFullPath(item.Folder)] = item;
                }
                catch (Exception ex)
                {
                    _status.Text = "Saved audit unavailable: " + ex.Message;
                }
            }
            _status.Text = $"Differential update: {_games.Count} entries ({_games.Count(g => g.Custom)} custom)" +
                (_libraryAudit.Count > 0 ? $" · {_libraryAudit.Count} saved audit results" : "");
            // Scan changes should update the list, not navigate to a selected game.
            // Keep this deterministic even if the previous page was Game Details.
            if (_currentSection == "Library")
                ShowLibrary();
        }
        catch (Exception ex) { _status.Text = $"Steam scan failed: {ex.Message}"; }
        finally { _busy = false; }
    }
}
