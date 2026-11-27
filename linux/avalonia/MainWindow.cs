using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.Primitives;
using Avalonia.Input;
using Avalonia.Layout;
using Avalonia.Media;
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
    private static readonly IBrush AccentBrush = Brush("#53BEEC");

    private readonly StackPanel _content = new() { Spacing = 16 };
    private readonly TextBlock _status = new() { Text = "Ready", Foreground = MutedBrush };
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
        FontWeight weight = default)
        => new()
        {
            Text = text,
            FontSize = size,
            Foreground = color ?? ForegroundBrush,
            FontWeight = weight,
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
            Foreground = primary ? Brush("#09131D") : ForegroundBrush,
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
        header.Children.Add(Text("AMDNR  /  Game library", 15, MutedBrush, FontWeight.SemiBold));
        var refresh = Button("↻  Refresh");
        refresh.Click += async (_, _) => await RefreshGamesAsync();
        Grid.SetColumn(refresh, 1);
        header.Children.Add(refresh);
        return header;
    }

    private void Clear(string section)
    {
        _content.Children.Clear();
        Highlight(section);
    }

    private void ShowLibrary()
    {
        Clear("Library");
        _content.Children.Add(Text("Your games", 30, ForegroundBrush, FontWeight.Bold));
        _content.Children.Add(Text("Detected Steam installations. Choose a game to manage its AMDNR files.",
            14, MutedBrush));
        var count = Text($"{_games.Count} games detected", 12, AccentBrush, FontWeight.SemiBold);
        _content.Children.Add(count);
        if (_games.Count == 0)
        {
            var empty = new StackPanel { Spacing = 12 };
            empty.Children.Add(Text("No Steam games detected", 20, ForegroundBrush, FontWeight.SemiBold));
            empty.Children.Add(Text("Install a game in Steam, refresh, or choose an executable manually from Install.",
                13, MutedBrush));
            var manual = Button("Choose an executable", true);
            manual.Click += (_, _) => ShowInstall();
            empty.Children.Add(manual);
            _content.Children.Add(Panel(empty));
            return;
        }
        foreach (var game in _games)
        {
            var row = new Grid { ColumnDefinitions = new ColumnDefinitions("*,Auto"), ColumnSpacing = 18 };
            var details = new StackPanel { Spacing = 5 };
            details.Children.Add(Text(game.Name, 17, ForegroundBrush, FontWeight.SemiBold));
            details.Children.Add(Text(game.Folder, 12, MutedBrush));
            row.Children.Add(details);
            var manage = Button("Manage  →");
            manage.Click += (_, _) => SelectGame(game);
            Grid.SetColumn(manage, 1);
            row.Children.Add(manage);
            _content.Children.Add(Panel(row, new Thickness(20, 16)));
        }
    }

    private void SelectGame(GameEntry game)
    {
        _selectedFolder = game.Folder;
        _exe = GuessExecutable(game.Folder);
        _status.Text = _exe is null
            ? $"Selected {game.Name}; select its game EXE manually."
            : $"Selected {game.Name}: {_exe}";
        ShowInstall();
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
            if (_navigation.TryGetValue("Library", out var selected) &&
                selected.Background == SurfaceBrush)
                ShowLibrary();
        }
        catch (Exception ex) { _status.Text = $"Steam scan failed: {ex.Message}"; }
        finally { _busy = false; }
    }
}
