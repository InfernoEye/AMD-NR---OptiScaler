using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.Primitives;
using Avalonia.Input;
using Avalonia.Interactivity;
using Avalonia.Threading;
using Avalonia.VisualTree;
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
    private static readonly IBrush BackgroundBrush = Brush("#111113");
    private static readonly IBrush SidebarBrush = Brush("#151519");
    private static readonly IBrush SurfaceBrush = Brush("#1E1E23");
    private static readonly IBrush LineBrush = Brush("#353039");
    private static readonly IBrush MutedBrush = Brush("#99969E");
    private static readonly IBrush ForegroundBrush = Brush("#F4F2F4");
    private static readonly IBrush AccentBrush = Brush("#C22E43");
    private static readonly IBrush AccentDarkBrush = Brush("#52202B");

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
    private JoystickNavigation? _controller;
    private string _libraryQuery = "";
    private bool _missingArtOnly;
    private StackPanel? _libraryResults;
    private TextBox? _librarySearch;
    private readonly Dictionary<string, LibraryAuditEntry> _libraryAudit = new(StringComparer.Ordinal);
    private readonly Dictionary<string, string> _indexedExecutables = new(StringComparer.Ordinal);
    private string _auditFilter = "All games";
    private bool _auditSnapshotLoaded;
    private readonly Grid _shell = new() { RowDefinitions = new RowDefinitions("54,*,30") };
    private Grid? _workspace;
    private Control? _sideNavigation;
    private Control? _topNavigation;
    private readonly Dictionary<string, Button> _horizontalNavigation = new();
    private bool _gridView = true;
    private Button? _gridViewButton;
    private Button? _listViewButton;
    private Button? _refreshButton;
    private OnboardingTour? _tour;
    private readonly string _onboardingPath = Path.Combine(
        Environment.GetEnvironmentVariable("XDG_CONFIG_HOME")
            ?? Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), ".config"),
        "amdnr-linux", "onboarding-v2.txt");
    private readonly string _viewStateFile = Path.Combine(
        Environment.GetEnvironmentVariable("XDG_CONFIG_HOME")
            ?? Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), ".config"),
        "amdnr-linux", "view-preference.txt");

    public MainWindow()
    {
        Title = "AMDNR Launcher";
        Width = 1120;
        Height = 750;
        MinWidth = 720;
        MinHeight = 450;
        // Never change window bounds in response to content changes.
        SizeToContent = SizeToContent.Manual;
        Background = BackgroundBrush;
        FontFamily = new FontFamily("Inter, Noto Sans, sans-serif");
        WindowStartupLocation = WindowStartupLocation.CenterScreen;

        _gridView = ReadViewPreference();
        var app = new Grid { ColumnDefinitions = new ColumnDefinitions("232,*") };
        _workspace = app;
        _sideNavigation = BuildSidebar();
        _topNavigation = BuildTopNavigation();
        var globalBar = BuildHeader();
        _shell.Children.Add(globalBar);
        Grid.SetRow(app, 1);
        _shell.Children.Add(app);
        // Steam Deck compact mode: keep navigation available at 800 px
        // logical width and let long sections wrap/scroll.
        SizeChanged += (_, e) =>
        {
            UpdateNavigationLayout(e.NewSize.Width);
        };
        KeyDown += (_, e) =>
        {
            if (_tour?.IsActive == true && e.Key == Key.Escape)
            {
                _tour.Close();
                e.Handled = true;
                return;
            }
            if (e.Key == Key.F5 && !_busy)
            {
                _ = RefreshGamesAsync();
                e.Handled = true;
            }
            else if (e.Key == Key.Escape && !_busy &&
                FocusManager?.GetFocusedElement() is not TextBox)
            {
                ShowLibrary();
                e.Handled = true;
            }
            else if (e.KeyModifiers.HasFlag(KeyModifiers.Control))
            {
                Action? page = e.Key switch
                {
                    Key.D1 => ShowLibrary,
                    Key.D2 => ShowInstalledGames,
                    Key.D3 => ShowInstall,
                    Key.D4 => ShowDoctor,
                    Key.D5 => ShowCompatibility,
                    Key.D6 => ShowSettings,
                    _ => null
                };
                if (page is not null)
                {
                    page();
                    e.Handled = true;
                }
            }
        };
        app.Children.Add(_sideNavigation);
        // Status lives in the header; the content viewport must never sit behind a footer.
        var main = new Grid { RowDefinitions = new RowDefinitions("*") };
        Grid.SetColumn(main, 1);
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
        Grid.SetRow(_pageScroller, 0);
        main.Children.Add(_pageScroller);
        app.Children.Add(main);
        var statusBar = new Grid
        {
            ColumnDefinitions = new ColumnDefinitions("*,Auto"),
            Background = SidebarBrush,
            Margin = new Thickness(0),
        };
        _status.Margin = new Thickness(18, 3, 10, 3);
        _status.VerticalAlignment = VerticalAlignment.Center;
        statusBar.Children.Add(_status);
        var runtimeLabel = Text("AMDNR LINUX  •  PROTON", 10, MutedBrush);
        runtimeLabel.Margin = new Thickness(12, 3, 18, 3);
        Grid.SetColumn(runtimeLabel, 1);
        statusBar.Children.Add(runtimeLabel);
        Grid.SetRow(statusBar, 2);
        _shell.Children.Add(statusBar);
        Content = _shell;
        _tour = new OnboardingTour(_shell, PrepareTourStep, ShowLibrary,
            () => _topNavigation?.IsVisible == true, _onboardingPath);
        UpdateNavigationLayout(Width);
        try { _backend = new Backend(); }
        catch (Exception ex) { _status.Text = ex.Message; }
        ShowLibrary();
        Closed += (_, _) => { _controller?.Dispose(); _controller = null; };
        Opened += async (_, _) =>
        {
            _controller ??= new JoystickNavigation(action => Dispatcher.UIThread.Post(() => OnControllerAction(action)));
            await LoadLauncherSettingsAsync();
            await RefreshGamesAsync();
            await ShowOnboardingAsync();
        };
    }

    private Task ShowOnboardingAsync(bool replay = false)
    {
        if (_tour is null) return Task.CompletedTask;
        if (!replay && _tour.HasBeenSeen) return Task.CompletedTask;
        _tour.Start();
        return Task.CompletedTask;
    }

    private Control TourNavigation(string section)
    {
        if (_sideNavigation?.IsVisible == true &&
            _navigation.TryGetValue(section, out var sidebar))
            return sidebar;
        if (_horizontalNavigation.TryGetValue(section, out var horizontal))
            return horizontal;
        return (Control?)_gridViewButton ?? _pageScroller;
    }

    private Control PrepareTourStep(int index)
    {
        // Tour visits real launcher pages before anchoring each visible control.
        // Never trigger an install, repair, download, or external configuration.
        switch (index)
        {
            case 0:
                ShowLibrary();
                return TourNavigation("Library");
            case 1:
                ShowLibrary();
                return _gridViewButton ?? TourNavigation("Library");
            case 2:
                ShowLibrary();
                return _librarySearch ?? TourNavigation("Library");
            case 3:
                ShowInstalledGames();
                return TourNavigation("Installed");
            case 4:
                ShowInstall();
                return TourNavigation("Install");
            case 5:
                ShowDoctor();
                return TourNavigation("Doctor");
            case 6:
                ShowSettings();
                return TourNavigation("Settings");
            default:
                ShowHelp();
                return TourNavigation("Help");
        }
    }

    private bool ReadViewPreference()
    {
        try
        {
            return !File.Exists(_viewStateFile) ||
                File.ReadAllText(_viewStateFile).Trim() != "list";
        }
        catch (IOException) { return true; }
        catch (UnauthorizedAccessException) { return true; }
    }

    private void SaveViewPreference()
    {
        try
        {
            var directory = Path.GetDirectoryName(_viewStateFile)!;
            Directory.CreateDirectory(directory);
            var temp = _viewStateFile + ".tmp";
            File.WriteAllText(temp, _gridView ? "grid\n" : "list\n");
            File.Move(temp, _viewStateFile, overwrite: true);
        }
        catch (IOException) { _status.Text = "View preference couldn't be saved."; }
        catch (UnauthorizedAccessException) { _status.Text = "View preference couldn't be saved."; }
    }

    private void SwitchLibraryView(bool grid)
    {
        if (_gridView == grid) return;
        _gridView = grid;
        SaveViewPreference();
        UpdateNavigationLayout(Bounds.Width > 0 ? Bounds.Width : Width);
        if (_currentSection == "Library" && _selectedGame is null)
            ShowLibrary();
    }

    private void UpdateNavigationLayout(double windowWidth)
    {
        if (_workspace is null || _sideNavigation is null || _topNavigation is null)
            return;
        var horizontal = !_gridView || windowWidth < 860;
        _sideNavigation.IsVisible = !horizontal;
        _topNavigation.IsVisible = horizontal;
        _breadcrumb.IsVisible = !horizontal;
        _workspace.ColumnDefinitions[0].Width = horizontal ? new GridLength(0)
            : new GridLength(windowWidth < 1040 ? 188 : 232);
    }

    private Control BuildTopNavigation()
    {
        var buttons = new StackPanel
        {
            Orientation = Orientation.Horizontal,
            Spacing = 5,
            Margin = new Thickness(3, 2),
        };
        AddTopNav(buttons, "Library", ShowLibrary);
        AddTopNav(buttons, "Installed", ShowInstalledGames);
        AddTopNav(buttons, "Install", ShowInstall);
        AddTopNav(buttons, "Doctor", ShowDoctor);
        AddTopNav(buttons, "Compatibility", ShowCompatibility);
        AddTopNav(buttons, "Settings", ShowSettings);
        AddTopNav(buttons, "Help", ShowHelp);
        return new ScrollViewer
        {
            Content = buttons,
            HorizontalScrollBarVisibility = ScrollBarVisibility.Auto,
            VerticalScrollBarVisibility = ScrollBarVisibility.Disabled,
            VerticalAlignment = VerticalAlignment.Center,
            HorizontalAlignment = HorizontalAlignment.Stretch,
        };
    }

    private void AddTopNav(StackPanel panel, string name, Action action)
    {
        var button = Button(NavIcon(name) + "  " + UiLanguage.Translate(name));
        button.Padding = new Thickness(9, 6);
        button.Click += (_, _) => action();
        _horizontalNavigation[name] = button;
        panel.Children.Add(button);
    }

    private void OnControllerAction(JoystickNavigation.Action action)
    {
        if (!IsActive) return;
        if (_tour?.IsActive == true)
        {
            if (action == JoystickNavigation.Action.Confirm) _tour.Next();
            else if (action == JoystickNavigation.Action.Back) _tour.Back();
            return;
        }
        if (action == JoystickNavigation.Action.Back)
        {
            // Gamepad B returns to the library, except while a modal window
            // owns focus; game installations never run on controller input alone.
            if (!_busy) ShowLibrary();
            return;
        }
        var focused = FocusManager?.GetFocusedElement();
        if (action == JoystickNavigation.Action.Confirm)
        {
            if (_busy) return;
            if (focused is Button button && button.IsEnabled)
                button.RaiseEvent(new RoutedEventArgs(Avalonia.Controls.Button.ClickEvent));
            else if (focused is ComboBox combo && combo.IsEnabled)
                combo.IsDropDownOpen = !combo.IsDropDownOpen;
            else if (focused is CheckBox checkbox && checkbox.IsEnabled)
                checkbox.IsChecked = !(checkbox.IsChecked ?? false);
            else if (focused is TextBox textbox && textbox.IsEnabled)
                textbox.Focus();
            return;
        }
        // Keyboard Tab order is a stable fallback for joystick layouts on
        // Avalonia 11.3.8, whose focus manager lacks spatial navigation.
        // Only visible, enabled, focusable controls can be selected.
        var candidates = this.GetVisualDescendants().OfType<Control>()
            .Where(control => control.Focusable && control.IsVisible && control.IsEnabled)
            .ToList();
        if (candidates.Count == 0) return;
        var index = candidates.FindIndex(control => ReferenceEquals(control, focused));
        var backwards = action is JoystickNavigation.Action.Up or JoystickNavigation.Action.Left;
        var next = index < 0 ? 0
            : (index + (backwards ? candidates.Count - 1 : 1)) % candidates.Count;
        candidates[next].Focus();
        // Keep focused controls visible when using a gamepad on long pages.
        candidates[next].BringIntoView();
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
            CornerRadius = new CornerRadius(9),
            Padding = padding ?? new Thickness(18),
            Child = child,
        };

    private static Button Button(string label, bool primary = false)
    {
        var control = new Button
        {
            Content = UiLanguage.TranslateButton(label),
            Padding = new Thickness(18, 10),
            Background = primary ? AccentBrush : SurfaceBrush,
            Foreground = ForegroundBrush,
            BorderBrush = primary ? AccentBrush : LineBrush,
            BorderThickness = new Thickness(1),
            CornerRadius = new CornerRadius(7),
            HorizontalAlignment = HorizontalAlignment.Left,
        };
        control.GotFocus += (_, _) =>
        {
            control.BorderBrush = ForegroundBrush;
            control.BorderThickness = new Thickness(2);
        };
        control.LostFocus += (_, _) =>
        {
            control.BorderBrush = control.Background == AccentDarkBrush
                ? AccentBrush : (primary ? AccentBrush : LineBrush);
            control.BorderThickness = new Thickness(1);
        };
        return control;
    }

    private static string NavIcon(string name) => name switch
    {
        "Library" => "▦",
        "Installed" => "✓",
        "Install" => "＋",
        "Doctor" => "✚",
        "Compatibility" => "◈",
        "Settings" => "⚙",
        "Help" => "?",
        _ => "·",
    };

    private static string NavLabel(string name) =>
        NavIcon(name) + "   " + UiLanguage.Translate(name).ToUpperInvariant();

    private Control BuildSidebar()
    {
        var stack = new StackPanel { Spacing = 6, Margin = new Thickness(10, 17) };
        stack.Children.Add(Text("WORKSPACE", 10, MutedBrush, FontWeight.Bold));
        stack.Children.Add(new Border { Height = 6 });
        AddNav(stack, "Library", ShowLibrary);
        AddNav(stack, "Installed", ShowInstalledGames);
        AddNav(stack, "Install", ShowInstall);
        AddNav(stack, "Doctor", ShowDoctor);
        stack.Children.Add(new Border { Height = 18 });
        stack.Children.Add(Text("SYSTEM", 10, MutedBrush, FontWeight.Bold));
        stack.Children.Add(new Border { Height = 4 });
        AddNav(stack, "Compatibility", ShowCompatibility);
        AddNav(stack, "Settings", ShowSettings);
        AddNav(stack, "Help", ShowHelp);
        stack.Children.Add(new Border { Height = 24 });
        stack.Children.Add(new Border
        {
            BorderBrush = LineBrush,
            BorderThickness = new Thickness(0, 1, 0, 0),
            Height = 15,
        });
        stack.Children.Add(Text("DEFAULT RUNTIME", 10, MutedBrush, FontWeight.Bold));
        stack.Children.Add(Text("AMDNR / OptiScaler", 12, ForegroundBrush));
        stack.Children.Add(Text("Linux + Proton · Setup is always reviewed",
            11, MutedBrush));
        return new Border
        {
            Background = SidebarBrush,
            BorderBrush = LineBrush,
            BorderThickness = new Thickness(0, 0, 1, 0),
            Child = new ScrollViewer
            {
                Content = stack,
                HorizontalScrollBarVisibility = ScrollBarVisibility.Disabled,
                VerticalScrollBarVisibility = ScrollBarVisibility.Auto,
            },
        };
    }

    private void AddNav(StackPanel stack, string name, Action action)
    {
        var button = new Button
        {
            Content = NavLabel(name),
            HorizontalContentAlignment = HorizontalAlignment.Left,
            HorizontalAlignment = HorizontalAlignment.Stretch,
            Padding = new Thickness(12, 12),
            Background = Brushes.Transparent,
            Foreground = ForegroundBrush,
            BorderBrush = Brushes.Transparent,
            BorderThickness = new Thickness(2, 0, 0, 0),
            CornerRadius = new CornerRadius(6),
        };
        button.Click += (_, _) => { action(); Highlight(name); };
        stack.Children.Add(button);
        _navigation[name] = button;
    }

    private void ApplyLanguage()
    {
        foreach (var (name, button) in _navigation)
            button.Content = NavLabel(name);
        foreach (var (name, button) in _horizontalNavigation)
            button.Content = NavIcon(name) + "  " + UiLanguage.Translate(name);
        if (_gridViewButton is not null)
            _gridViewButton.Content = "▦ " + UiLanguage.Translate("Grid");
        if (_listViewButton is not null)
            _listViewButton.Content = "☰ " + UiLanguage.Translate("List");
        if (_refreshButton is not null)
            _refreshButton.Content = "↻  " + UiLanguage.Translate("Refresh");
        if (_currentSection == "Settings") ShowSettings();
        else if (_currentSection == "Library")
        {
            if (_selectedGame is not null) ShowGameDetails();
            else ShowLibrary();
        }
        else if (_currentSection == "Help") ShowHelp();
        else _status.Text = UiLanguage.Current == "pl"
            ? "Język zmieniony. Otwórz ponownie bieżącą stronę, aby odświeżyć etykiety."
            : "Language changed. Reopen this page to refresh labels.";
    }

    private void Highlight(string selected)
    {
        foreach (var (name, button) in _navigation)
        {
            button.Background = name == selected ? AccentDarkBrush : Brushes.Transparent;
            button.Foreground = name == selected ? ForegroundBrush : MutedBrush;
            button.BorderBrush = name == selected ? AccentBrush : Brushes.Transparent;
        }
        foreach (var (name, button) in _horizontalNavigation)
        {
            button.Background = name == selected ? AccentDarkBrush : SurfaceBrush;
            button.Foreground = name == selected ? ForegroundBrush : MutedBrush;
            button.BorderBrush = name == selected ? AccentBrush : LineBrush;
        }
    }

    private Control BuildHeader()
    {
        // The global toolbar matches the reference launcher hierarchy:
        // brand at left, current workspace, compact mode/actions at right.
        var header = new Grid
        {
            ColumnDefinitions = new ColumnDefinitions("88,*,Auto"),
            Background = BackgroundBrush,
            ColumnSpacing = 10,
            Margin = new Thickness(15, 5, 15, 4),
        };
        var logo = new StackPanel { Spacing = -5, VerticalAlignment = VerticalAlignment.Center };
        logo.Children.Add(Text("AMD", 16, ForegroundBrush, FontWeight.Bold));
        logo.Children.Add(Text("NR", 21, AccentBrush, FontWeight.Bold));
        header.Children.Add(logo);
        _breadcrumb.FontSize = 12;
        _breadcrumb.Foreground = MutedBrush;
        _breadcrumb.VerticalAlignment = VerticalAlignment.Center;
        Grid.SetColumn(_breadcrumb, 1);
        header.Children.Add(_breadcrumb);
        Grid.SetColumn(_topNavigation, 1);
        header.Children.Add(_topNavigation);
        _status.FontSize = 11;
        _status.MaxLines = 1;
        _status.TextTrimming = TextTrimming.CharacterEllipsis;

        var headerActions = new StackPanel
        {
            Orientation = Orientation.Horizontal,
            Spacing = 5,
            VerticalAlignment = VerticalAlignment.Center,
        };
        var gridView = Button("▦ " + UiLanguage.Translate("Grid"));
        var listView = Button("☰ " + UiLanguage.Translate("List"));
        _gridViewButton = gridView;
        _listViewButton = listView;
        gridView.Padding = new Thickness(10, 6);
        listView.Padding = new Thickness(10, 6);
        gridView.Click += (_, _) => SwitchLibraryView(true);
        listView.Click += (_, _) => SwitchLibraryView(false);
        void SetViewColors()
        {
            gridView.Background = _gridView ? AccentBrush : SurfaceBrush;
            listView.Background = !_gridView ? AccentBrush : SurfaceBrush;
        }
        SetViewColors();
        gridView.Click += (_, _) => SetViewColors();
        listView.Click += (_, _) => SetViewColors();
        headerActions.Children.Add(gridView);
        headerActions.Children.Add(listView);
        var refresh = Button("↻", false);
        _refreshButton = refresh;
        refresh.Padding = new Thickness(12, 6);
        refresh.Click += async (_, _) =>
        {
            _selectedGame = null;
            await RefreshGamesAsync();
        };
        headerActions.Children.Add(refresh);
        Grid.SetColumn(headerActions, 2);
        header.Children.Add(headerActions);
        return new Border
        {
            Background = BackgroundBrush,
            BorderBrush = LineBrush,
            BorderThickness = new Thickness(0, 0, 0, 1),
            Child = header,
        };
    }

    private void Clear(string section)
    {
        _content.Children.Clear();
        _currentSection = section;
        _breadcrumb.Text = "AMDNR  /  " + UiLanguage.Translate(section);
        Highlight(section);
        // Navigation returns to the beginning of the new page; user-sized
        // window dimensions are intentionally unchanged.
        _pageScroller.Offset = new Vector(0, 0);
    }

    private void ShowHelp()
    {
        Clear("Help");
        bool polish = UiLanguage.Current == "pl";
        _content.Children.Add(Text(UiLanguage.Translate("Help") + " / FAQ",
            29, ForegroundBrush, FontWeight.Bold));
        _content.Children.Add(Text(polish
            ? "Porady dotyczące instalacji AMDNR i Protona. Ta strona nie instaluje sterowników ani nie zmienia opcji Steam."
            : "Practical guidance for AMDNR installation and Proton troubleshooting. This page does not install drivers or change Steam options.",
            14, MutedBrush));

        void Question(string enTitle, string enAnswer, string plTitle, string plAnswer)
        {
            var stack = new StackPanel { Spacing = 8 };
            stack.Children.Add(Text(polish ? plTitle : enTitle, 17, ForegroundBrush, FontWeight.SemiBold));
            stack.Children.Add(Text(polish ? plAnswer : enAnswer, 13, MutedBrush));
            _content.Children.Add(Panel(stack));
        }

        Question("How do I install AMDNR safely?",
            "Select a game in Library, confirm its Windows executable and choose Install. Review the official release ZIP and proxy DLL; downloads are checked and backups saved. Steam launch options remain under your control.",
            "Jak bezpiecznie zainstalować AMDNR?",
            "Wybierz grę w Bibliotece, potwierdź plik Windows .exe i przejdź do Instalacji. Sprawdź oficjalny ZIP i bibliotekę proxy DLL. Launcher weryfikuje pobierane pliki i tworzy kopie zapasowe. Opcje Steam zmieniasz samodzielnie.");
        Question("Why does AMDNR not appear in my game?",
            "Check the Windows build under Proton, the correct executable and proxy DLL alias. Copy the suggested WINEDLLOVERRIDES into Steam launch options only if appropriate. Doctor explains possible errors.",
            "Dlaczego AMDNR nie pojawia się w grze?",
            "Sprawdź wersję Windows uruchamianą przez Proton, prawidłowy plik .exe i nazwę proxy DLL. W razie potrzeby samodzielnie skopiuj proponowane WINEDLLOVERRIDES do opcji Steam. Diagnostyka pomoże znaleźć błąd.");
        Question("What about lmxxf and Daniel?",
            "lmxxf has community reports of neural rendering on compatible AMD GPUs and Proton versions; results vary. Daniel 0.6.0 is not independently game-validated here. Daniel 0.8.0 is currently unsupported on Linux.",
            "Co z lmxxf i Danielem?",
            "Użytkownicy zgłaszają działanie lmxxf na zgodnych GPU AMD i wersjach Protona; wyniki są różne. Daniel 0.6.0 nie został tu niezależnie zweryfikowany w grze. Daniel 0.8.0 nie jest obecnie obsługiwany na Linuksie.");
        Question("How do I recover or remove an installation?",
            "Installed and Doctor check tracked files. Recovery/Repair protects earlier files and refuses uncertain changes. Managed uninstall restores backups. Do not remove recovery journals by hand.",
            "Jak naprawić lub usunąć instalację?",
            "Zainstalowane i Diagnostyka sprawdzają pliki. Naprawa i odzyskiwanie chronią wcześniejsze pliki oraz odmawiają niepewnych zmian. Bezpieczne odinstalowanie przywraca kopie zapasowe. Nie usuwaj ręcznie dzienników odzyskiwania.");
        Question("Why can't the AppImage start?",
            "Mark the AppImage executable. On systems without FUSE use --appimage-extract-and-run. Linux desktop libraries and GPU drivers are still required; .NET and Python are bundled.",
            "Dlaczego AppImage nie uruchamia się?",
            "Ustaw AppImage jako plik wykonywalny. Bez FUSE użyj --appimage-extract-and-run. Nadal potrzebne są biblioteki pulpitu Linux i sterowniki GPU; .NET i Python są dołączone.");
        Question("What belongs in a bug report?",
            "Include distro, desktop session, GPU, Proton version, game, steps and a redacted Doctor support report. Check it before sharing; never publish credentials or private game files.",
            "Co zamieścić w zgłoszeniu błędu?",
            "Podaj dystrybucję, środowisko graficzne, GPU, wersję Protona, grę, kroki odtworzenia i zanonimizowany raport Diagnostyki. Sprawdź raport przed wysłaniem. Nie publikuj haseł ani prywatnych plików.");
        var actions = new WrapPanel { ItemSpacing = 10, LineSpacing = 8 };
        var doctor = Button(UiLanguage.Translate("Doctor").ToUpperInvariant(), true);
        doctor.Click += (_, _) => ShowDoctor();
        actions.Children.Add(doctor);
        var introduction = Button(UiLanguage.Translate("Replay introduction").ToUpperInvariant());
        introduction.Click += async (_, _) => await ShowOnboardingAsync(replay: true);
        actions.Children.Add(introduction);
        var credits = Button("COMMUNITY RESEARCH / CREDITS");
        credits.Click += (_, _) =>
        {
            try
            {
                Process.Start(new ProcessStartInfo
                {
                    FileName = "https://github.com/hassanm0301/AMDNR-Linux",
                    UseShellExecute = true,
                });
            }
            catch (Exception ex) { _status.Text = "Could not open credits: " + ex.Message; }
        };
        actions.Children.Add(credits);
        _content.Children.Add(actions);
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
            var healthTools = new WrapPanel { ItemSpacing = 10, LineSpacing = 8 };
            var verifyAll = Button("VERIFY ALL INSTALLED FILES", true);
            var healthResults = new StackPanel { Spacing = 8 };
            verifyAll.Click += async (_, _) =>
            {
                if (_backend is null || _busy) return;
                _busy = true;
                verifyAll.IsEnabled = false;
                _status.Text = "Verifying tracked AMDNR files and backups…";
                healthResults.Children.Clear();
                try
                {
                    var healthy = 0;
                    var attention = 0;
                    foreach (var game in installed)
                    {
                        if (game.Status != "recorded") continue;
                        var report = await _backend.InstallationAsync(game.Executable);
                        if (_currentSection != "Installed") return;
                        var good = report.Status == "healthy";
                        if (good) healthy++; else attention++;
                        healthResults.Children.Add(Text(
                            (good ? "✓  " : "!  ") + game.Name + " · " +
                            report.Status + (report.Status == "invalid_record"
                                ? ": " + report.Error
                                : $" · {report.Verified}/{report.Files} verified, " +
                                  $"{report.Missing} missing, {report.Modified} modified, " +
                                  $"{report.BackupsMissing} missing backups"),
                            13, good ? AccentBrush : ForegroundBrush));
                    }
                    _status.Text = $"Verified {healthy + attention} installations: " +
                        $"{healthy} healthy, {attention} need attention.";
                }
                catch (Exception ex) { _status.Text = "Verification stopped: " + ex.Message; }
                finally { _busy = false; verifyAll.IsEnabled = true; }
            };
            healthTools.Children.Add(verifyAll);
            results.Children.Add(healthTools);
            results.Children.Add(healthResults);
            var releaseTools = new StackPanel { Spacing = 9 };
            releaseTools.Children.Add(Text("RELEASE / UPDATE MANAGEMENT",
                12, AccentBrush, FontWeight.Bold));
            releaseTools.Children.Add(Text("Compare recorded archive names with published builds. " +
                "Download a verified ZIP to prepare a manual update. No live game files are " +
                "replaced automatically.", 12, MutedBrush));
            var builds = new ComboBox
            {
                MinWidth = 350, MaxWidth = 720,
                PlaceholderText = "Check upstream releases",
                HorizontalAlignment = HorizontalAlignment.Left,
            };
            var compareText = Text("No release check performed.", 13, MutedBrush);
            var check = Button("CHECK AVAILABLE VERSIONS");
            check.Click += async (_, _) =>
            {
                if (_backend is null || _busy) return;
                _busy = true;
                check.IsEnabled = false;
                try
                {
                    var candidates = await _backend.ReleasesAsync();
                    var visible = _launcherSettings?.ShowPrereleases == true
                        ? candidates : candidates.Where(x => !x.Prerelease).ToList();
                    if (_currentSection != "Installed") return;
                    builds.ItemsSource = visible;
                    builds.SelectedIndex = visible.Count > 0 ? 0 : -1;
                    if (visible.Count == 0)
                    {
                        compareText.Text = "No releases available.";
                    }
                    else
                    {
                        var latest = visible[0];
                        var matching = installed.Count(game =>
                            string.Equals(Path.GetFileName(game.SourceArchive ?? ""),
                                latest.Asset, StringComparison.OrdinalIgnoreCase));
                        compareText.Text = $"Latest listed package: {latest.Tag} / {latest.Asset}. " +
                            $"{matching} of {installed.Count} indexed installation records " +
                            "match this archive name. Other records may be older, custom " +
                            "or unknown; no automatic upgrade is performed.";
                    }
                    _status.Text = $"Loaded {visible.Count} published releases.";
                }
                catch (Exception ex) { _status.Text = "Version lookup failed: " + ex.Message; }
                finally { _busy = false; check.IsEnabled = true; }
            };
            releaseTools.Children.Add(check);
            releaseTools.Children.Add(builds);
            releaseTools.Children.Add(compareText);
            var fetch = Button("DOWNLOAD VERIFIED BUILD");
            fetch.Click += async (_, _) =>
            {
                if (_backend is null || _busy || builds.SelectedItem is not ReleaseEntry chosen)
                    return;
                _busy = true;
                fetch.IsEnabled = false;
                try
                {
                    var (exit, result) = await _backend.RunAsync(new[]
                    {
                        "--download-release", chosen.Tag, "--release-asset", chosen.Asset
                    });
                    if (exit != 0) throw new InvalidOperationException(result);
                    var path = result.Trim();
                    if (!File.Exists(path)) throw new IOException("Downloaded archive is missing");
                    _archive = path;
                    _status.Text = "Verified " + chosen.Asset +
                        ". Select a game and use Install for manual version changes.";
                    compareText.Text = "Verified archive prepared: " + path;
                }
                catch (Exception ex) { _status.Text = "Release download failed: " + ex.Message; }
                finally { _busy = false; fetch.IsEnabled = true; }
            };
            releaseTools.Children.Add(fetch);
            var manageVersions = Button("OPEN INSTALL & MANAGE");
            manageVersions.Click += (_, _) => ShowInstall();
            releaseTools.Children.Add(manageVersions);
            releaseTools.Children.Add(Text("For a recorded installation, use Verify first. " +
                "The installer requires an explicit uninstall/restore before a new package; " +
                "there is no automatic update or rollback.", 12, MutedBrush));
            results.Children.Add(Panel(releaseTools));
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
                var manageInstall = Button("MANAGE / RESTORE");
                manageInstall.Click += (_, _) =>
                {
                    _exe = entry.Executable;
                    _selectedGame = game;
                    _selectedFolder = entry.Folder;
                    ShowInstall();
                };
                actions.Children.Add(manageInstall);
                var oneResult = Text("", 12, MutedBrush);
                var verifyOne = Button("VERIFY FILES");
                verifyOne.Click += async (_, _) =>
                {
                    if (_busy || _backend is null) return;
                    _busy = true;
                    verifyOne.IsEnabled = false;
                    oneResult.Text = "Verifying tracked files…";
                    try
                    {
                        var report = await _backend.InstallationAsync(entry.Executable);
                        oneResult.Text = report.Status == "healthy"
                            ? $"✓  {report.Verified}/{report.Files} files verified; backups present"
                            : $"!  {report.Status} · {report.Missing} missing · " +
                                $"{report.Modified} modified · " +
                                $"{report.BackupsMissing} missing backups";
                        _status.Text = "Verification complete for " + entry.Name;
                    }
                    catch (Exception ex) { oneResult.Text = "Verification failed: " + ex.Message; }
                    finally { _busy = false; verifyOne.IsEnabled = true; }
                };
                actions.Children.Add(verifyOne);
                var folder = Button("OPEN FOLDER");
                folder.Click += (_, _) => OpenGameFolder(entry.Folder);
                actions.Children.Add(folder);
                details.Children.Add(actions);
                details.Children.Add(oneResult);
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
        _content.Children.Add(Text(UiLanguage.Translate("Your library").ToUpperInvariant(),
            27, ForegroundBrush, FontWeight.Bold));
        _content.Children.Add(Text(
            $"{_games.Count} games in library  ·  Steam / Heroic / Lutris / Custom",
            12, MutedBrush));
        var libraryTabs = new WrapPanel { ItemSpacing = 6, LineSpacing = 7 };
        void AddLibraryTab(string key, string display)
        {
            var tab = Button(display, _auditFilter == key);
            tab.Padding = new Thickness(12, 6);
            tab.Click += (_, _) =>
            {
                _auditFilter = key;
                ShowLibrary();
            };
            libraryTabs.Children.Add(tab);
        }
        AddLibraryTab("All games", UiLanguage.Translate("All games"));
        AddLibraryTab("AMDNR recorded", UiLanguage.Translate("Installed"));
        AddLibraryTab("Windows ready", UiLanguage.Translate("Windows ready"));
        _content.Children.Add(libraryTabs);

        var toolbar = new Grid { ColumnDefinitions = new ColumnDefinitions("*,Auto,Auto"), ColumnSpacing = 12 };
        _librarySearch = new TextBox
        {
            Text = _libraryQuery,
            Watermark = UiLanguage.Translate("Search your games…"),
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
        var missing = Button(UiLanguage.Translate(_missingArtOnly ? "Show all" : "Missing art").ToUpperInvariant());
        missing.Click += (_, _) =>
        {
            _missingArtOnly = !_missingArtOnly;
            ShowLibrary();
        };
        Grid.SetColumn(missing, 1);
        toolbar.Children.Add(missing);
        var manual = Button("+  " + UiLanguage.Translate("Add manually"));
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
        var auditButton = Button(UiLanguage.Translate(_libraryAudit.Count > 0
            ? "Rescan library" : "Analyze library").ToUpperInvariant(), true);
        auditButton.Click += async (_, _) => await AuditLibraryAsync(auditButton);
        auditControls.Children.Add(auditButton);
        var filters = new ComboBox
        {
            ItemsSource = new[] { "All games", "Windows ready", "Native Linux",
                "Needs attention", "AMDNR recorded" }.Select(UiLanguage.Translate).ToArray(),
            SelectedItem = UiLanguage.Translate(_auditFilter),
            MinWidth = 200,
            HorizontalAlignment = HorizontalAlignment.Left,
        };
        filters.SelectionChanged += (_, _) =>
        {
            var localized = filters.SelectedItem?.ToString() ?? UiLanguage.Translate("All games");
            _auditFilter = new[] { "All games", "Windows ready", "Native Linux",
                "Needs attention", "AMDNR recorded" }
                .FirstOrDefault(key => UiLanguage.Translate(key) == localized) ?? "All games";
            RenderLibraryResults();
        };
        auditControls.Children.Add(filters);
        auditBar.Children.Add(auditControls);
        _content.Children.Add(new Expander
        {
            Header = "LIBRARY HEALTH  /  AUDIT AND READINESS FILTERS",
            IsExpanded = false,
            Background = SurfaceBrush,
            Content = Panel(auditBar, new Thickness(13)),
        });

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

        if (_gridView)
        {
            var tiles = new WrapPanel
            {
                Orientation = Orientation.Horizontal,
                ItemSpacing = 12,
                LineSpacing = 12,
            };
            foreach (var game in filtered)
                tiles.Children.Add(BuildGameTile(game));
            _libraryResults.Children.Add(tiles);
        }
        else
        {
            foreach (var game in filtered)
                _libraryResults.Children.Add(BuildGameCard(game));
        }
    }

    private Control BuildGameTile(GameEntry game)
    {
        // Artwork first, like the official launcher; all actions remain
        // keyboard/controller accessible and never install on selection.
        var stack = new StackPanel { Width = 292, Spacing = 7 };
        var artFrame = new Grid { Height = 178, ClipToBounds = true };
        artFrame.Children.Add(GameArtwork(game, 178, fill: true));
        var artHeader = new Border
        {
            Background = Brush("#DB161418"),
            Padding = new Thickness(9, 5),
            VerticalAlignment = VerticalAlignment.Top,
            Child = new Grid
            {
                ColumnDefinitions = new ColumnDefinitions("*,Auto"),
                Children =
                {
                    Text("●  AMDNR LINUX", 10, AccentBrush, FontWeight.Bold),
                },
            },
        };
        var platformText = Text(game.Custom ? "CUSTOM" : "STEAM", 10, MutedBrush);
        Grid.SetColumn(platformText, 1);
        ((Grid)artHeader.Child!).Children.Add(platformText);
        artFrame.Children.Add(artHeader);
        stack.Children.Add(artFrame);

        var info = new Grid { ColumnDefinitions = new ColumnDefinitions("*,Auto"),
            ColumnSpacing = 8, Margin = new Thickness(3, 0, 3, 0) };
        var details = new StackPanel { Spacing = 3 };
        var title = Text(game.Name, 15, ForegroundBrush, FontWeight.SemiBold);
        title.MaxLines = 2;
        details.Children.Add(title);
        if (_libraryAudit.TryGetValue(Path.GetFullPath(game.Folder), out var audit))
        {
            details.Children.Add(Text(audit.InstalledRecord ? "● AMDNR recorded" :
                audit.Status == "windows_ready" ? "● Windows game ready" :
                audit.Status == "native_linux" ? "● Native Linux" :
                "○ Needs review", 11, audit.InstalledRecord ? AccentBrush : MutedBrush));
        }
        else
            details.Children.Add(Text(game.Custom ? "Custom game" : "Steam game",
                11, MutedBrush));
        info.Children.Add(details);
        var choose = Button("→", true);
        choose.VerticalAlignment = VerticalAlignment.Center;
        choose.Padding = new Thickness(13, 9);
        choose.ToolTip = null;
        choose.Click += (_, _) => SelectGame(game);
        Grid.SetColumn(choose, 1);
        info.Children.Add(choose);
        stack.Children.Add(info);

        var tile = Panel(stack, new Thickness(9));
        tile.PointerEntered += (_, _) =>
        {
            tile.BorderBrush = AccentBrush;
            choose.Content = UiLanguage.Current == "pl" ? "WYBIERZ →" : "SELECT →";
        };
        tile.PointerExited += (_, _) =>
        {
            tile.BorderBrush = LineBrush;
            if (!choose.IsFocused) choose.Content = "→";
        };
        choose.GotFocus += (_, _) =>
        {
            tile.BorderBrush = AccentBrush;
            choose.Content = UiLanguage.Current == "pl" ? "WYBIERZ →" : "SELECT →";
        };
        choose.LostFocus += (_, _) =>
        {
            tile.BorderBrush = LineBrush;
            choose.Content = "→";
        };
        return tile;
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

        var manage = Button(UiLanguage.Translate("Select game").ToUpperInvariant() + "  →", true);
        manage.VerticalAlignment = VerticalAlignment.Center;
        manage.Click += (_, _) => SelectGame(game);
        Grid.SetColumn(manage, 2);
        row.Children.Add(manage);
        var card = Panel(row, new Thickness(15));
        card.PointerEntered += (_, _) => card.BorderBrush = AccentBrush;
        card.PointerExited += (_, _) => card.BorderBrush = LineBrush;
        return card;
    }

    private Control GameArtwork(GameEntry game, double height, bool fill = false)
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
                        Stretch = fill ? Stretch.UniformToFill : Stretch.Uniform,
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

        var back = Button("←  " + UiLanguage.Translate("All games back").ToUpperInvariant());
        back.Click += (_, _) => ShowLibrary();
        _content.Children.Add(back);

        // Artwork remains decorative; game modifications always require explicit action.
        var hero = new Grid { MinHeight = 265, ClipToBounds = true };
        hero.Children.Add(GameArtwork(game, 310, fill: true));
        hero.Children.Add(new Border
        {
            Background = Brush("#DB111113"),
            IsHitTestVisible = false,
        });
        var summary = new StackPanel
        {
            Spacing = 10,
            Margin = new Thickness(22, 18),
            VerticalAlignment = VerticalAlignment.Center,
            HorizontalAlignment = HorizontalAlignment.Stretch,
        };
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
        var actions = new WrapPanel { ItemSpacing = 10, LineSpacing = 8 };
        var install = Button(UiLanguage.Translate(installed
            ? "Manage installation" : "Install AMDNR").ToUpperInvariant(), true);
        install.IsEnabled = _exe is not null && File.Exists(_exe);
        install.Click += (_, _) => ShowInstall();
        actions.Children.Add(install);
        var doctor = Button(UiLanguage.Translate("Doctor").ToUpperInvariant());
        doctor.Click += (_, _) => ShowDoctor();
        actions.Children.Add(doctor);
        summary.Children.Add(actions);
        if (_exe is not null && File.Exists(_exe))
        {
            var configure = Button(UiLanguage.Translate("Configure AMDNR").ToUpperInvariant());
            configure.Click += (_, _) => ShowGameConfiguration();
            summary.Children.Add(configure);
            var extensions = Button(UiLanguage.Translate("Manage extensions").ToUpperInvariant());
            extensions.Click += (_, _) => ShowExtensions();
            summary.Children.Add(extensions);
        }
        var coverButton = Button(UiLanguage.Translate("Change cover art").ToUpperInvariant());
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
        hero.Children.Add(summary);
        _content.Children.Add(new Border
        {
            Child = hero,
            BorderBrush = LineBrush,
            BorderThickness = new Thickness(1),
            CornerRadius = new CornerRadius(10),
            ClipToBounds = true,
        });

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
        _content.Children.Add(Text("Choose a game, review the verified package and DLL name, then confirm installation. " +
            "Nothing changes in Steam settings automatically.", 14, MutedBrush));
        var instructions = new StackPanel { Spacing = 7 };
        instructions.Children.Add(Text("1  SELECT YOUR GAME", 12, AccentBrush, FontWeight.SemiBold));
        instructions.Children.Add(Text("2  REVIEW THE DOWNLOAD AND PROXY DLL", 12, MutedBrush));
        instructions.Children.Add(Text("3  CONFIRM CHANGES AND KEEP YOUR BACKUPS", 12, MutedBrush));
        instructions.Children.Add(Text("Steam launch options remain a copyable preview. " +
            "Daniel's Proton runtime is not verified; lmxxf is the preferred Linux testing option.",
            12, MutedBrush));
        _content.Children.Add(Panel(instructions, new Thickness(14)));

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
        var quickInstall = Button("QUICK INSTALL LATEST VERIFIED AMDNR", true);
        section.Children.Add(quickInstall);
        section.Children.Add(Text(
            "Automatically selects the newest eligible official AMDNR ZIP, verifies its SHA-256, " +
            "and installs it for the selected Windows executable using your preferred proxy DLL. " +
            "Existing game files are backed up; an existing AMDNR installation must be managed via Update.",
            12, MutedBrush));
        quickInstall.Click += async (_, _) =>
        {
            if (_busy || _backend is null || string.IsNullOrWhiteSpace(_exe) ||
                !File.Exists(_exe))
            {
                _status.Text = "Select the game's Windows executable before quick install.";
                return;
            }
            if (HasInstallRecord())
            {
                _status.Text = "AMDNR already installed. Use Repair / Update rather than overwriting it.";
                return;
            }
            _busy = true;
            quickInstall.IsEnabled = false;
            string? verifiedArchive = null;
            try
            {
                var entries = await _backend.ReleasesAsync();
                var latest = (_launcherSettings?.ShowPrereleases == true
                    ? entries : entries.Where(x => !x.Prerelease)).FirstOrDefault();
                if (latest is null)
                    throw new InvalidOperationException("No verified official AMDNR release found.");
                _status.Text = "Downloading and verifying official AMDNR: " + latest.Asset;
                var (exit, output) = await _backend.RunAsync(new[]
                { "--download-release", latest.Tag, "--release-asset", latest.Asset });
                if (exit != 0) throw new InvalidOperationException(output);
                verifiedArchive = output.Trim();
                if (!File.Exists(verifiedArchive))
                    throw new FileNotFoundException("Verified release archive unavailable.");
            }
            catch (Exception ex) { _status.Text = "Quick install failed: " + ex.Message; }
            finally
            {
                _busy = false;
                quickInstall.IsEnabled = true;
            }
            if (verifiedArchive is not null)
            {
                _archive = verifiedArchive;
                if (_archiveBox is not null) _archiveBox.Text = verifiedArchive;
                await ExecuteAsync(true);
            }
        };

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
        var maintenanceSection = new StackPanel { Spacing = 10 };
        maintenanceSection.Children.Add(Text("REPAIR / UPDATE / RECOVERY", 12, AccentBrush, FontWeight.Bold));
        maintenanceSection.Children.Add(Text(
            "Repair restores files from the exact recorded package. Update verifies the selected ZIP, " +
            "keeps original game backups and records changes for crash recovery. " +
            "Modified files require explicit approval; an interrupted transaction must be recovered first.",
            12, MutedBrush));
        var maintenanceActions = new WrapPanel { ItemSpacing = 10, LineSpacing = 8 };
        var autoRepair = Button("REPAIR INSTALLED FILES", true);
        var update = Button("UPDATE USING SELECTED ZIP");
        var reviewRepair = Button("BACK UP CHANGES & REPAIR");
        var recover = Button("RESTORE INTERRUPTED UPDATE");
        var nextProxy = Button("TRY NEXT PROXY");
        var copyNewLaunchOptions = Button("COPY SAFE STEAM OPTIONS");
        copyNewLaunchOptions.IsEnabled = false;
        string? composedSteamOptions = null;
        maintenanceActions.Children.Add(autoRepair);
        maintenanceActions.Children.Add(update);
        maintenanceActions.Children.Add(reviewRepair);
        maintenanceActions.Children.Add(recover);
        maintenanceActions.Children.Add(nextProxy);
        maintenanceActions.Children.Add(copyNewLaunchOptions);
        copyNewLaunchOptions.Click += async (_, _) =>
        {
            if (composedSteamOptions is not null)
                await CopyToClipboardAsync(composedSteamOptions,
                    "Merged Steam launch options copied; paste into Steam manually.");
        };
        maintenanceSection.Children.Add(maintenanceActions);
        var maintenanceResult = Text(
            "No maintenance operation has been run. Verify installed files first.", 12, MutedBrush);
        maintenanceSection.Children.Add(maintenanceResult);
        async Task RunMaintenance(params string[] args)
        {
            if (_busy || _backend is null || string.IsNullOrWhiteSpace(_exe) || !File.Exists(_exe))
            {
                _status.Text = "Select a valid installed game first.";
                return;
            }
            _busy = true;
            foreach (var button in new[] { autoRepair, update, reviewRepair, recover, nextProxy })
                button.IsEnabled = false;
            _status.Text = "Checking managed files and applying safe maintenance…";
            try
            {
                var command = new List<string>(args) { "--exe", _exe };
                var (exit, output) = await _backend.RunAsync(command);
                maintenanceResult.Text = output.Trim();
                _status.Text = exit == 0 ? "Maintenance completed; review the result below."
                                         : "Maintenance safely refused; see the result below.";
                if (exit == 0)
                {
                    if (args.Length > 0 && args[0] == "--try-next-proxy")
                    {
                        composedSteamOptions = null;
                        copyNewLaunchOptions.IsEnabled = false;
                        var alias = RecordedAlias(_exe);
                        if (!string.IsNullOrWhiteSpace(alias) &&
                            !alias.EndsWith(".asi", StringComparison.OrdinalIgnoreCase))
                        {
                            try
                            {
                                var folder = _selectedGame?.Folder ??
                                    Path.GetDirectoryName(_exe)!;
                                var options = await _backend.SteamUserOptionsAsync(folder, alias);
                                if (!string.IsNullOrWhiteSpace(options.Preview))
                                {
                                    composedSteamOptions = options.Preview;
                                    copyNewLaunchOptions.IsEnabled = true;
                                    maintenanceResult.Text += "\nMerged Steam launch preview: " +
                                        composedSteamOptions;
                                }
                                else
                                    maintenanceResult.Text +=
                                        "\nSteam options ambiguous; review them manually before launching.";
                            }
                            catch (Exception ex)
                            {
                                maintenanceResult.Text += "\nSteam preview unavailable: " + ex.Message;
                            }
                        }
                    }
                    RefreshInstallStatus();
                    try
                    {
                        var report = await _backend.InstallationAsync(_exe);
                        maintenanceResult.Text += "\nIntegrity: " + report.Status +
                            " · Missing " + report.Missing + " · Modified " + report.Modified;
                    }
                    catch { /* The maintenance result remains available. */ }
                }
            }
            catch (Exception ex) { _status.Text = "Maintenance failed: " + ex.Message; }
            finally
            {
                _busy = false;
                foreach (var button in new[] { autoRepair, update, reviewRepair, recover, nextProxy })
                    button.IsEnabled = true;
                RefreshInstallStatus();
            }
        }
        autoRepair.Click += async (_, _) => await RunMaintenance("--repair-auto");
        update.Click += async (_, _) =>
        {
            if (string.IsNullOrWhiteSpace(_archive) || !File.Exists(_archive))
            {
                _status.Text = "Select the replacement AMDNR ZIP above before updating.";
                return;
            }
            await RunMaintenance("--update-from", _archive);
        };
        reviewRepair.Click += async (_, _) => await RunMaintenance("--repair-auto", "--backup-modified");
        recover.Click += async (_, _) => await RunMaintenance("--recover-transaction");
        nextProxy.Click += async (_, _) => await RunMaintenance("--try-next-proxy");
        section.Children.Add(Panel(maintenanceSection));
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
        var diagnosticActions = new WrapPanel { ItemSpacing = 10, LineSpacing = 8 };
        var bundle = Button("COLLECT REDACTED SUPPORT REPORT");

        var diagnosticDetails = new StackPanel { Spacing = 6 };
        diagnosticActions.Children.Add(bundle);
        _content.Children.Add(diagnosticActions);
        _content.Children.Add(Panel(diagnosticDetails));
        bundle.Click += async (_, _) =>
        {
            if (_busy || _backend is null || string.IsNullOrWhiteSpace(_exe) || !File.Exists(_exe))
            {
                _status.Text = "Select the game executable first.";
                return;
            }
            _busy = true;
            bundle.IsEnabled = false;
            try
            {
                var (exit, output) = await _backend.RunAsync(new[]
                { "--support-bundle", "--exe", _exe });
                if (exit != 0) throw new InvalidOperationException(output);
                using var doc = JsonDocument.Parse(output);
                var filename = doc.RootElement.GetProperty("file").GetString() ?? "";
                diagnosticDetails.Children.Clear();
                diagnosticDetails.Children.Add(Text("Support report saved locally: " + filename, 13));
                diagnosticDetails.Children.Add(Text(
                    "Review the ZIP before sharing. It includes redacted logs and diagnostic metadata; " +
                    "nothing is uploaded automatically.", 12, MutedBrush));
                _status.Text = "Local support report created.";
            }
            catch (Exception ex) { _status.Text = "Support report failed: " + ex.Message; }
            finally { _busy = false; bundle.IsEnabled = true; }
        };
        _content.Children.Add(Text("These are launcher-environment checks, not a verification of " +
            "GPU compatibility, rendering quality, or the Windows DLL runtime under Proton.",
            13, MutedBrush));
    }

    private async void ShowCompatibility()
    {
        Clear("Compatibility");
        _content.Children.Add(Text("Linux / Proton compatibility", 30, ForegroundBrush, FontWeight.Bold));
        _content.Children.Add(Text(
            "Inspect GPU, Proton tools, active game processes and possible anti-cheat. " +
            "Nothing here changes Steam or installs GPU drivers.", 13, MutedBrush));
        var exe = _exe;
        var folder = _selectedGame?.Folder ?? _selectedFolder;
        if (string.IsNullOrWhiteSpace(folder) && !string.IsNullOrWhiteSpace(exe))
            folder = Path.GetDirectoryName(exe);
        if (_backend is null || string.IsNullOrWhiteSpace(folder) || !Directory.Exists(folder))
        {
            _content.Children.Add(Text(
                "Select a game in Library first. A remembered Windows executable enables full diagnostics.",
                14, MutedBrush));
            return;
        }
        var gameFolder = folder;
        var panel = new StackPanel { Spacing = 12 };
        var scan = Button("RUN COMPATIBILITY CHECK", true);
        var scanOutput = Text("No compatibility checks run yet.", 12, MutedBrush);
        panel.Children.Add(scan);
        panel.Children.Add(scanOutput);
        _content.Children.Add(Panel(panel));
        scan.Click += async (_, _) =>
        {
            if (_busy || _backend is null || string.IsNullOrWhiteSpace(exe) || !File.Exists(exe))
            {
                _status.Text = "Select a Windows game executable to check compatibility.";
                return;
            }
            _busy = true;
            scan.IsEnabled = false;
            try
            {
                var (exit, result) = await _backend.RunAsync(new[]
                { "--compatibility-json", "--exe", exe });
                if (exit != 0) throw new InvalidOperationException(result);
                using var doc = JsonDocument.Parse(result);
                var root = doc.RootElement;
                var gpu = root.GetProperty("gpu").EnumerateArray().Select(e =>
                    e.GetProperty("vendor").GetString() + " (" + e.GetProperty("pci_id").GetString() +
                    "; driver " + e.GetProperty("driver").GetString() + ")").ToArray();
                var proton = root.GetProperty("proton_tools").EnumerateArray().Select(e =>
                    e.GetProperty("name").GetString()).ToArray();
                var antiCheat = root.GetProperty("anti_cheat");
                var process = root.GetProperty("game_process");
                var warnings = root.GetProperty("blockers").EnumerateArray().Select(e => e.GetString()).ToArray();
                scanOutput.Text =
                    "GPU: " + (gpu.Length == 0 ? "Not detected" : string.Join(", ", gpu)) +
                    "\nProton tools: " + (proton.Length == 0 ? "Not detected" : string.Join(", ", proton)) +
                    "\nGame running (heuristic): " +
                        (process.GetProperty("running").ValueKind == JsonValueKind.Null ? "Unknown" :
                            process.GetProperty("running").GetBoolean() ? "Possibly" : "Not detected") +
                    "\nAnti-cheat files: " + (antiCheat.GetProperty("potential_anti_cheat").GetBoolean()
                        ? string.Join(", ", antiCheat.GetProperty("filenames").EnumerateArray()
                            .Select(e => e.GetString())) : "No known filenames detected") +
                    "\nRuntime confidence: " + root.GetProperty("verdict").GetString() +
                    "\nNeuralHub: " + root.GetProperty("daniel_080").GetString() +
                    (warnings.Length == 0 ? "" : "\nWarnings: " + string.Join(" | ", warnings));
                _status.Text = "Compatibility checks completed. In-game rendering still requires testing.";
            }
            catch (Exception ex) { _status.Text = "Compatibility scan failed: " + ex.Message; }
            finally { _busy = false; scan.IsEnabled = true; }
        };

        var profile = new StackPanel { Spacing = 11 };
        profile.Children.Add(Text("PER-GAME PROTON PROFILE", 12, AccentBrush, FontWeight.Bold));
        profile.Children.Add(Text(
            "These preferences are saved only in the launcher. Steam compatibility-tool selection " +
            "must be applied in Steam itself; launch options remain copy-only.",
            12, MutedBrush));
        var gameMode = new CheckBox { Content = "Use GameMode (gamemoderun)", Foreground = ForegroundBrush };
        var mangoHud = new CheckBox { Content = "Use MangoHud", Foreground = ForegroundBrush };
        profile.Children.Add(gameMode);
        profile.Children.Add(mangoHud);
        profile.Children.Add(Text("PREFERRED PROTON (informational)", 11, MutedBrush));
        var protonField = new TextBox { Text = "Steam default",
            Background = BackgroundBrush, Foreground = ForegroundBrush };
        profile.Children.Add(protonField);
        profile.Children.Add(Text("TESTED RUNTIME", 11, MutedBrush));
        var runtime = new TextBox { Watermark = "e.g. mochizuki",
            Background = BackgroundBrush, Foreground = ForegroundBrush };
        profile.Children.Add(runtime);
        var statuses = new[] { "unverified", "files_present", "detected_in_game",
            "rendering_confirmed", "failed" };
        var tested = new ComboBox { ItemsSource = statuses, SelectedItem = "unverified",
            Width = 260, HorizontalAlignment = HorizontalAlignment.Left };
        profile.Children.Add(tested);
        var profileButtons = new WrapPanel { ItemSpacing = 10, LineSpacing = 8 };
        var save = Button("SAVE GAME PROFILE");
        var preview = Button("COPY SAFE STEAM PREVIEW");
        profileButtons.Children.Add(save);
        profileButtons.Children.Add(preview);
        profile.Children.Add(profileButtons);
        _content.Children.Add(Panel(profile));
        try
        {
            var (exit, result) = await _backend.RunAsync(new[]
                { "--proton-profile-json", gameFolder });
            if (_currentSection != "Compatibility" || exit != 0) return;
            using var doc = JsonDocument.Parse(result);
            var settings = doc.RootElement;
            gameMode.IsChecked = settings.GetProperty("gamemode").GetBoolean();
            mangoHud.IsChecked = settings.GetProperty("mangohud").GetBoolean();
            protonField.Text = settings.GetProperty("selected_proton").GetString();
            runtime.Text = settings.GetProperty("tested_runtime").ValueKind == JsonValueKind.Null
                ? "" : settings.GetProperty("tested_runtime").GetString();
            tested.SelectedItem = settings.GetProperty("tested_result").GetString();
        }
        catch (Exception ex) { _status.Text = "Could not read Proton profile: " + ex.Message; }
        save.Click += async (_, _) =>
        {
            if (_busy || _backend is null) return;
            _busy = true;
            save.IsEnabled = false;
            try
            {
                var payload = JsonSerializer.Serialize(new {
                    gamemode = gameMode.IsChecked == true,
                    mangohud = mangoHud.IsChecked == true,
                    selected_proton = protonField.Text ?? "Steam default",
                    tested_runtime = string.IsNullOrWhiteSpace(runtime.Text) ? null : runtime.Text,
                    tested_result = tested.SelectedItem?.ToString() ?? "unverified",
                });
                var (exit, result) = await _backend.RunAsync(new[]
                    { "--save-proton-profile", gameFolder, "--profile-json", payload });
                if (exit != 0) throw new InvalidOperationException(result);
                _status.Text = "Per-game Proton preferences saved; Steam settings unchanged.";
            }
            catch (Exception ex) { _status.Text = "Proton preferences rejected: " + ex.Message; }
            finally { _busy = false; save.IsEnabled = true; }
        };
        preview.Click += async (_, _) =>
        {
            if (_busy || _backend is null) return;
            _busy = true;
            preview.IsEnabled = false;
            try
            {
                var alias = !string.IsNullOrWhiteSpace(exe)
                    ? RecordedAlias(exe) ?? _alias : _alias;
                var (exit, output) = await _backend.RunAsync(new[]
                    { "--proton-options-json", gameFolder, "--alias", alias });
                if (exit != 0) throw new InvalidOperationException(output);
                using var doc = JsonDocument.Parse(output);
                var data = doc.RootElement;
                if (data.GetProperty("status").GetString() != "ok")
                    throw new InvalidOperationException(data.GetProperty("reason").GetString() ??
                        "Existing Steam launch options need manual review.");
                var value = data.GetProperty("launch_options").GetString();
                if (value is null) throw new InvalidOperationException("No safe launch preview.");
                await CopyToClipboardAsync(value, "Steam launch preview copied; apply it manually in Steam.");
            }
            catch (Exception ex) { _status.Text = "Steam preview unavailable: " + ex.Message; }
            finally { _busy = false; preview.IsEnabled = true; }
        };
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
        // Official release components are independent from local ASI plugins.
        var official = new StackPanel { Spacing = 11 };
        official.Children.Add(Text("OFFICIAL AMDNR COMPONENTS", 12, AccentBrush, FontWeight.Bold));
        official.Children.Add(Text(
            "Download from 3zwr1/AMD-NR---OptiScaler. ZIPs are SHA-256 verified. " +
            "Review files before installation. Differing files require explicit backed-up replacement.",
            12, MutedBrush));
        var checkRuntimes = Button("CHECK GAME RUNTIME FILES");
        var runtimeReport = new StackPanel { Spacing = 5 };
        checkRuntimes.Click += async (_, _) =>
        {
            if (_busy || _backend is null) return;
            _busy = true;
            checkRuntimes.IsEnabled = false;
            runtimeReport.Children.Clear();
            try
            {
                var report = await _backend.RuntimeDiagnosticsAsync(selected);
                if (_exe != selected || _breadcrumb.Text != "AMDNR  /  Extensions") return;
                runtimeReport.Children.Add(Text(report, 12, MutedBrush));
                _status.Text = "Runtime file inspection completed; no game files changed.";
            }
            catch (Exception ex) { _status.Text = "Runtime inspection failed: " + ex.Message; }
            finally { _busy = false; checkRuntimes.IsEnabled = true; }
        };
        official.Children.Add(checkRuntimes);
        var prepareMochi = Button("PREPARE MOCHI MODEL (LOCAL NVIDIA DLL)");
        var fetchMochi = Button("USE UNOFFICIAL MIRROR & PREPARE MOCHI");
        official.Children.Add(Text(
            "Mochi 0.0.9 needs a locally prepared model. Select your own " +
            "nvngx_dlssnr.dll 310.9.16 or 310.8.0 (or a ZIP containing it). " +
            "The Linux extractor verifies source and model weights; NVIDIA files are never downloaded by this action.",
            12, MutedBrush));
        official.Children.Add(prepareMochi);
        official.Children.Add(Text(
            "Optional third-party source: RankFTW/rhi-repo. Not operated by NVIDIA or AMDNR; " +
            "redistribution authorization has not been verified. By choosing the button below, " +
            "you request a temporary download of that community mirror's pinned ZIP. " +
            "The ZIP and NVIDIA DLL must BOTH match fixed SHA-256 values before local model preparation. " +
            "No NVIDIA binary is installed or kept. Manual import above remains available.",
            12, MutedBrush));
        official.Children.Add(fetchMochi);
        official.Children.Add(runtimeReport);
        fetchMochi.Click += async (_, _) =>
        {
            if (_busy || _backend is null) return;
            _busy = true;
            fetchMochi.IsEnabled = false;
            prepareMochi.IsEnabled = false;
            _status.Text = "Verifying optional community ZIP + NVIDIA DLL, preparing local Mochi model…";
            try
            {
                var report = await _backend.PrepareMochiFromCommunityAsync(selected);
                if (_exe != selected || _breadcrumb.Text != "AMDNR  /  Extensions") return;
                runtimeReport.Children.Clear();
                runtimeReport.Children.Add(Text(report, 12, ForegroundBrush));
                runtimeReport.Children.Add(Text(
                    await _backend.RuntimeDiagnosticsAsync(selected), 12, MutedBrush));
                _status.Text = "Verified Mochi model prepared. Restart Deadlock to test runtime availability.";
            }
            catch (Exception ex)
            {
                _status.Text = "Community model preparation refused: " + ex.Message;
            }
            finally
            {
                _busy = false;
                fetchMochi.IsEnabled = true;
                prepareMochi.IsEnabled = true;
            }
        };
        prepareMochi.Click += async (_, _) =>
        {
            if (_busy || _backend is null) return;
            var input = await PickFileAsync(
                "Select your own NVIDIA nvngx_dlssnr.dll or ZIP (310.9.16 / 310.8.0)",
                new FilePickerFileType("NVIDIA DLSS-NR input")
                { Patterns = new[] { "nvngx_dlssnr.dll", "*.zip" } });
            if (string.IsNullOrWhiteSpace(input)) return;
            _busy = true;
            prepareMochi.IsEnabled = false;
            _status.Text = "Verifying input and locally preparing Mochi Model A/B…";
            try
            {
                var report = await _backend.PrepareMochiModelAsync(selected, input);
                if (_exe != selected || _breadcrumb.Text != "AMDNR  /  Extensions") return;
                runtimeReport.Children.Clear();
                runtimeReport.Children.Add(Text(report, 12, ForegroundBrush));
                runtimeReport.Children.Add(Text(
                    await _backend.RuntimeDiagnosticsAsync(selected), 12, MutedBrush));
                _status.Text = "Mochi models prepared. Restart the game to test runtime availability.";
            }
            catch (Exception ex)
            {
                _status.Text = "Mochi model preparation refused: " + ex.Message;
            }
            finally { _busy = false; prepareMochi.IsEnabled = true; }
        };
        var componentPicker = new ComboBox
        {
            PlaceholderText = "Load official AMDNR components",
            HorizontalAlignment = HorizontalAlignment.Stretch,
        };
        official.Children.Add(componentPicker);
        var componentActions = new WrapPanel { ItemSpacing = 10, LineSpacing = 8 };
        var loadComponents = Button("LOAD OFFICIAL COMPONENTS");
        var previewComponent = Button("DOWNLOAD & PREVIEW");
        var installComponent = Button("INSTALL PREVIEWED COMPONENT", true);
        var replaceComponent = Button("BACK UP & REPLACE CONFLICTS");
        previewComponent.IsEnabled = false;
        installComponent.IsEnabled = false;
        replaceComponent.IsEnabled = false;
        componentActions.Children.Add(loadComponents);
        componentActions.Children.Add(previewComponent);
        componentActions.Children.Add(installComponent);
        componentActions.Children.Add(replaceComponent);
        official.Children.Add(componentActions);
        var previewDetails = new StackPanel { Spacing = 6 };
        official.Children.Add(previewDetails);
        var managedComponents = new StackPanel { Spacing = 9 };
        official.Children.Add(Text("INSTALLED RELEASE COMPONENTS", 12, AccentBrush, FontWeight.Bold));
        official.Children.Add(managedComponents);
        _content.Children.Add(Panel(official));

        // Daniel has its own version manager rather than sharing the
        // Mochi/lmxxf/WrongGPU archive selector or install controls.
        var danielSection = new StackPanel { Spacing = 11 };
        danielSection.Children.Add(Text("DANIEL NEURAL RUNTIMES", 12, AccentBrush, FontWeight.Bold));
        danielSection.Children.Add(Text(
            "Official Daniel releases: select one runtime version per game. " +
            "To switch versions, remove the old managed runtime first so backups are restored. " +
            "Daniel 0.8.0 requires NeuralHub data and Windows-specific GPU services " +
            "that are not yet supported by this Linux launcher under Proton. " +
            "Choose a version and select Set Up Selected Daniel. The launcher handles " +
            "downloads, verification, installation and managed removal. " +
            "NeuralHub 0.8.0 is currently unavailable under Proton because required " +
            "Windows GPU driver interfaces are missing.", 12, MutedBrush));
        var danielPicker = new ComboBox
        {
            PlaceholderText = "Load Daniel runtime versions",
            HorizontalAlignment = HorizontalAlignment.Stretch,
        };
        danielSection.Children.Add(danielPicker);
        var danielButtons = new WrapPanel { ItemSpacing = 10, LineSpacing = 8 };
        var loadDaniel = Button("LOAD DANIEL VERSIONS");
        var previewDaniel = Button("SET UP SELECTED DANIEL", true);
        var replaceDaniel = Button("BACK UP & REPLACE DANIEL FILES");
        previewDaniel.IsEnabled = false;
        replaceDaniel.IsEnabled = false;
        danielButtons.Children.Add(loadDaniel);
        danielButtons.Children.Add(previewDaniel);
        danielButtons.Children.Add(replaceDaniel);
        danielSection.Children.Add(danielButtons);
        var danielPreviewDetails = new StackPanel { Spacing = 6 };
        danielSection.Children.Add(danielPreviewDetails);
        danielSection.Children.Add(Text("INSTALLED DANIEL RUNTIME", 12, AccentBrush, FontWeight.Bold));
        var installedDaniel = new StackPanel { Spacing = 8 };
        danielSection.Children.Add(installedDaniel);
        _content.Children.Add(Panel(danielSection));

        async Task ReloadManagedComponents()
        {
            if (_backend is null) return;
            managedComponents.Children.Clear();
            installedDaniel.Children.Clear();
            try
            {
                var installed = await _backend.InstalledComponentsAsync(selected);
                if (_exe != selected || _breadcrumb.Text != "AMDNR  /  Extensions") return;
                if (!installed.Any(x => !IsDanielRuntime(x.Asset)))
                    managedComponents.Children.Add(Text("No launcher-managed release components.",
                        12, MutedBrush));
                if (!installed.Any(x => IsDanielRuntime(x.Asset)))
                    installedDaniel.Children.Add(Text("No managed Daniel runtime installed.",
                        12, MutedBrush));
                foreach (var component in installed)
                {
                    var item = component;
                    var entry = new StackPanel { Spacing = 6 };
                    entry.Children.Add(Text(item.Asset + " · " + item.FileCount +
                        " files · " + item.Tag, 13, ForegroundBrush, FontWeight.SemiBold));
                    if (item.Modified.Count > 0)
                    {
                        entry.Children.Add(Text("Modified/missing files: " +
                            string.Join(", ", item.Modified.Take(5)) +
                            " — removal blocked", 12, MutedBrush));
                    }
                    else
                    {
                        var remove = Button("REMOVE COMPONENT");
                        remove.Click += async (_, _) =>
                        {
                            if (_busy || _backend is null) return;
                            _busy = true;
                            remove.IsEnabled = false;
                            try
                            {
                                await _backend.RemoveComponentAsync(selected, item.Asset);
                                _status.Text = "Removed component: " + item.Asset;
                            }
                            catch (Exception ex) { _status.Text = "Removal refused: " + ex.Message; }
                            finally { _busy = false; await ReloadManagedComponents(); }
                        };
                        entry.Children.Add(remove);
                    }
                    var destination = IsDanielRuntime(item.Asset) ? installedDaniel : managedComponents;
                    destination.Children.Add(Panel(entry, new Thickness(10)));
                }
            }
            catch (Exception ex)
            {
                managedComponents.Children.Add(Text(
                    "Component inventory unavailable: " + ex.Message, 12, MutedBrush));
                installedDaniel.Children.Add(Text("Daniel inventory unavailable.", 12, MutedBrush));
            }
        }

        string? previewedTag = null;
        string? previewedAsset = null;
        bool previewReplaceable = false;
        componentPicker.SelectionChanged += (_, _) =>
        {
            previewedTag = null;
            previewedAsset = null;
            previewReplaceable = false;
            installComponent.IsEnabled = false;
            replaceComponent.IsEnabled = false;
            previewDetails.Children.Clear();
            previewComponent.IsEnabled = componentPicker.SelectedItem is ReleaseEntry;
        };
        loadComponents.Click += async (_, _) =>
        {
            if (_busy || _backend is null) return;
            _busy = true;
            loadComponents.IsEnabled = false;
            try
            {
                var entries = await _backend.ComponentsAsync();
                var visible = (_launcherSettings?.ShowPrereleases == true
                    ? entries : entries.Where(x => !x.Prerelease))
                    .Where(x => !IsDanielRuntime(x.Asset)).ToArray();
                if (_exe != selected || _breadcrumb.Text != "AMDNR  /  Extensions") return;
                componentPicker.ItemsSource = visible;
                componentPicker.SelectedIndex = visible.Length > 0 ? 0 : -1;
                _status.Text = visible.Length + " official AMDNR component packages found.";
            }
            catch (Exception ex) { _status.Text = "Component lookup failed: " + ex.Message; }
            finally { _busy = false; loadComponents.IsEnabled = true; }
        };
        previewComponent.Click += async (_, _) =>
        {
            if (_busy || _backend is null || componentPicker.SelectedItem is not ReleaseEntry chosen)
                return;
            _busy = true;
            previewComponent.IsEnabled = false;
            installComponent.IsEnabled = false;
            replaceComponent.IsEnabled = false;
            previewedTag = null;
            previewedAsset = null;
            previewReplaceable = false;
            previewDetails.Children.Clear();
            _status.Text = "Downloading and verifying official component…";
            try
            {
                var result = await _backend.PreviewComponentAsync(selected, chosen.Tag, chosen.Asset);
                if (_exe != selected || _breadcrumb.Text != "AMDNR  /  Extensions") return;
                previewDetails.Children.Add(Text(result.FileCount + " archive files · " +
                    (result.ExtractedBytes / (1024.0 * 1024 * 1024)).ToString("F2") +
                    " GiB extracted. Sample paths: " + string.Join(", ", result.Files.Take(12)) +
                    (result.FileCount > 12 ? "…" : ""), 12, MutedBrush));
                previewDetails.Children.Add(Text(
                    result.NewFileCount + " new files · " + result.IdenticalCount +
                    " identical existing files (preserved) · " + result.ConflictCount +
                    " differing/unsafe files (installation blocked)", 12, MutedBrush));
                if (result.SafetyLimitExceeded)
                {
                    previewDetails.Children.Add(Text(
                        "SAFETY BLOCK: " +
                        (result.TooManyFiles ? "Archive has over 10,000 files. " : "") +
                        "Extraction limits: 12 GiB total, 8 GiB per file, 10,000 files. " +
                        "Preview only; installation disabled.", 13, AccentBrush, FontWeight.Bold));
                    foreach (var file in result.LargestFiles)
                        previewDetails.Children.Add(Text(file.Name + " — " +
                            (file.Bytes / (1024.0 * 1024 * 1024)).ToString("F2") +
                            " GiB unpacked", 12, MutedBrush));
                }
                if (result.Conflicts.Count > 0)
                    previewDetails.Children.Add(Text(result.ConflictCount +
                        " existing files differ: " +
                        string.Join(", ", result.Conflicts.Take(8)), 12, MutedBrush));
                if (!result.SafetyLimitExceeded &&
                    result.ConflictCount > 0 &&
                    result.ConflictCount == result.ReplaceableCount)
                {
                    previewedTag = chosen.Tag;
                    previewedAsset = chosen.Asset;
                    previewReplaceable = true;
                    replaceComponent.IsEnabled = true;
                    previewDetails.Children.Add(Text(
                        "Backed-up replacement is optional. Originals are stored outside the game " +
                        "and restored on removal if replacements remain unchanged. " +
                        "The base AMDNR Doctor may report modified tracked files.",
                        12, MutedBrush));
                }
                else if (result.Installable)
                {
                    previewedTag = chosen.Tag;
                    previewedAsset = chosen.Asset;
                    installComponent.IsEnabled = true;
                }
                _status.Text = result.Installable
                    ? "Component verified. Existing identical files will be preserved."
                    : result.SafetyLimitExceeded
                        ? "Archive size exceeds extraction limits; inspect the largest files below."
                        : "Component install blocked by existing files.";
            }
            catch (Exception ex) { _status.Text = "Component preview failed: " + ex.Message; }
            finally { _busy = false; previewComponent.IsEnabled = true; }
        };
        // Distinct Daniel version selection with independent preview/install state.
        string? previewedDanielTag = null;
        string? previewedDanielAsset = null;
        bool danielCanReplace = false;
        bool IsDanielRuntime(string asset) =>
            asset.StartsWith("v", StringComparison.OrdinalIgnoreCase) &&
            asset.EndsWith("-Runtime.zip", StringComparison.OrdinalIgnoreCase) &&
            asset.Length > "v0.0.0-Runtime.zip".Length - 1;
        danielPicker.SelectionChanged += (_, _) =>
        {
            previewedDanielTag = null;
            previewedDanielAsset = null;
            danielCanReplace = false;
            replaceDaniel.IsEnabled = false;
            danielPreviewDetails.Children.Clear();
            previewDaniel.IsEnabled = danielPicker.SelectedItem is ReleaseEntry;
        };
        async Task LoadDanielVersions()
        {
            if (_busy || _backend is null) return;
            _busy = true;
            loadDaniel.IsEnabled = false;
            try
            {
                var entries = await _backend.ComponentsAsync();
                var versions = entries.Where(x => IsDanielRuntime(x.Asset) &&
                    (_launcherSettings?.ShowPrereleases == true || !x.Prerelease)).ToArray();
                if (_exe != selected || _breadcrumb.Text != "AMDNR  /  Extensions") return;
                danielPicker.ItemsSource = versions;
                // Prefer a supported legacy package on Linux. Newer NeuralHub
                // versions remain selectable but are not presented as ready
                // until their Windows AMD driver dependencies work under Proton.
                danielPicker.SelectedItem = versions.FirstOrDefault(
                    x => x.Asset == "v0.6.0-Runtime.zip") ??
                    versions.FirstOrDefault();
                _status.Text = versions.Length + " official Daniel runtimes found. " +
                    "Choose a version and select Set Up Selected Daniel.";
            }
            catch (Exception ex) { _status.Text = "Daniel versions unavailable: " + ex.Message; }
            finally { _busy = false; loadDaniel.IsEnabled = true; }
        };
        loadDaniel.Click += async (_, _) => await LoadDanielVersions();
        previewDaniel.Click += async (_, _) =>
        {
            if (_busy || _backend is null || danielPicker.SelectedItem is not ReleaseEntry chosen)
                return;
            _busy = true;
            previewDaniel.IsEnabled = false;
            replaceDaniel.IsEnabled = false;
            danielCanReplace = false;
            previewedDanielTag = null;
            previewedDanielAsset = null;
            danielPreviewDetails.Children.Clear();
            _status.Text = "Verifying official Daniel " + chosen.Name + " package…";
            try
            {
                if (chosen.Asset == "v0.8.0-Runtime.zip")
                {
                    danielPreviewDetails.Children.Add(Text(
                        "Daniel 0.8.0 is a NeuralHub host, not a legacy pass-DLL package. " +
                        "It requires AMDNR-NeuralHub-080 setup, a data index, and " +
                        "GPU/driver interfaces not provided by the current Proton integration. " +
                        "Automatic installation is blocked to avoid a false success report. " +
                        "The launcher will support this version once the required " +
                        "Proton GPU bridge exists; no files were changed.",
                        12, MutedBrush));
                    _status.Text = "Daniel 0.8.0 cannot initialize under current Proton GPU bridge.";
                }
                else
                {
                    var result = await _backend.PreviewComponentAsync(selected, chosen.Tag, chosen.Asset);
                    if (_exe != selected || _breadcrumb.Text != "AMDNR  /  Extensions" ||
                        !ReferenceEquals(danielPicker.SelectedItem, chosen)) return;
                    danielPreviewDetails.Children.Add(Text(
                        result.FileCount + " Daniel runtime files · " +
                        result.NewFileCount + " new · " +
                        result.IdenticalCount + " identical · " +
                        result.ConflictCount + " conflicting. " +
                        string.Join(", ", result.Files.Take(12)), 12, MutedBrush));
                    if (result.Conflicts.Count > 0)
                        danielPreviewDetails.Children.Add(Text(
                            "Conflicts: " + string.Join(", ", result.Conflicts.Take(10)),
                            12, MutedBrush));
                    if (result.Installable)
                    {
                        // The selected version's entire supported pipeline runs from
                        // this one action; never silently replace differing files.
                        await _backend.InstallComponentAsync(selected, chosen.Tag, chosen.Asset);
                        _status.Text = chosen.Name + " files installed and tracked. " +
                            "Restart the game to test runtime initialization.";
                        danielPreviewDetails.Children.Add(Text(
                            "Setup complete. Verified package files are tracked for safe removal.",
                            12, MutedBrush));
                        await ReloadManagedComponents();
                    }
                    else if (!result.SafetyLimitExceeded &&
                             result.ConflictCount > 0 &&
                             result.ConflictCount == result.ReplaceableCount)
                    {
                        previewedDanielTag = chosen.Tag;
                        previewedDanielAsset = chosen.Asset;
                        danielCanReplace = true;
                        replaceDaniel.IsEnabled = true;
                        danielPreviewDetails.Children.Add(Text(
                            "Some files differ from those already installed. The launcher " +
                            "can back up the originals before replacing them. " +
                            "No files were changed yet.", 12, MutedBrush));
                        _status.Text = "Daniel setup needs approval to back up and replace existing files.";
                    }
                    else
                        _status.Text = "Daniel setup blocked by existing files or safety checks.";
                }
            }
            catch (Exception ex) { _status.Text = "Daniel preview refused: " + ex.Message; }
            finally { _busy = false; previewDaniel.IsEnabled = true; }
        };
        async Task InstallSelectedDaniel()
        {
            if (_busy || _backend is null || danielPicker.SelectedItem is not ReleaseEntry chosen ||
                previewedDanielTag != chosen.Tag || previewedDanielAsset != chosen.Asset ||
                !danielCanReplace)
                return;
            _busy = true;
            replaceDaniel.IsEnabled = false;
            try
            {
                await _backend.InstallComponentAsync(selected, chosen.Tag, chosen.Asset,
                    replaceConflicts: true);
                _status.Text = "Daniel runtime installed: " + chosen.Name +
                    ". Restart the game to test initialization.";
                previewedDanielTag = null;
                previewedDanielAsset = null;
                danielCanReplace = false;
                danielPreviewDetails.Children.Clear();
            }
            catch (Exception ex) { _status.Text = "Daniel installation refused: " + ex.Message; }
            finally { _busy = false; await ReloadManagedComponents(); }
        }
        replaceDaniel.Click += async (_, _) => await InstallSelectedDaniel();
        installComponent.Click += async (_, _) =>
        {
            if (_busy || _backend is null || componentPicker.SelectedItem is not ReleaseEntry chosen ||
                previewedTag != chosen.Tag || previewedAsset != chosen.Asset)
                return;
            _busy = true;
            installComponent.IsEnabled = false;
            try
            {
                await _backend.InstallComponentAsync(selected, chosen.Tag, chosen.Asset);
                _status.Text = "Component files installed: " + chosen.Asset +
                    ". Neural runtime detection is checked separately.";
                runtimeReport.Children.Clear();
                try
                {
                    runtimeReport.Children.Add(Text(
                        await _backend.RuntimeDiagnosticsAsync(selected), 12, MutedBrush));
                }
                catch (Exception ex)
                {
                    runtimeReport.Children.Add(Text(
                        "Files installed; runtime diagnostics unavailable: " + ex.Message,
                        12, MutedBrush));
                }
                previewedTag = null;
                previewedAsset = null;
                previewDetails.Children.Clear();
            }
            catch (Exception ex) { _status.Text = "Component installation refused: " + ex.Message; }
            finally { _busy = false; await ReloadManagedComponents(); }
        };
        replaceComponent.Click += async (_, _) =>
        {
            if (_busy || _backend is null || !previewReplaceable ||
                componentPicker.SelectedItem is not ReleaseEntry chosen ||
                previewedTag != chosen.Tag || previewedAsset != chosen.Asset)
                return;
            _busy = true;
            replaceComponent.IsEnabled = false;
            installComponent.IsEnabled = false;
            try
            {
                await _backend.InstallComponentAsync(selected, chosen.Tag, chosen.Asset,
                    replaceConflicts: true);
                _status.Text = "Component files installed: " + chosen.Asset +
                    "; replaced originals backed up. Runtime presence checked below.";
                runtimeReport.Children.Clear();
                try
                {
                    runtimeReport.Children.Add(Text(
                        await _backend.RuntimeDiagnosticsAsync(selected), 12, MutedBrush));
                }
                catch (Exception ex)
                {
                    runtimeReport.Children.Add(Text(
                        "Files installed; runtime diagnostics unavailable: " + ex.Message,
                        12, MutedBrush));
                }
                previewedTag = null;
                previewedAsset = null;
                previewReplaceable = false;
                previewDetails.Children.Clear();
            }
            catch (Exception ex) { _status.Text = "Backup-aware install refused: " + ex.Message; }
            finally { _busy = false; await ReloadManagedComponents(); }
        };
        await ReloadManagedComponents();
        await LoadDanielVersions();

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

            };
            var guidePanel = new StackPanel { Spacing = 11 };
            void RenderGuided()
            {
                guidePanel.Children.Clear();
                guidePanel.Children.Add(Text(UiLanguage.Translate("Guided settings").ToUpperInvariant(),
                    12, AccentBrush, FontWeight.Bold));
                guidePanel.Children.Add(Text(
                    "Only supported keys already present under [DlssNr] appear here. " +
                    "Changes update the preview below; nothing is written until SAVE CONFIGURATION. " +
                    "Unknown INI lines and comments are preserved.",
                    12, MutedBrush));
                var known = GuidedIniEditor.Read(editor.Text ?? "");
                if (known.Count == 0)
                {
                    guidePanel.Children.Add(Text(
                        "No supported existing neural settings detected in this INI. " +
                        "The raw editor remains available. No unsupported settings will be inserted.",
                        13, MutedBrush));
                }
                foreach (var setting in known)
                {
                    var settingRow = new StackPanel { Spacing = 6 };
                    settingRow.Children.Add(Text(setting.Key, 14, ForegroundBrush, FontWeight.SemiBold));
                    settingRow.Children.Add(Text(setting.Description, 12, MutedBrush));
                    var choices = new ComboBox
                    {
                        ItemsSource = setting.Choices,
                        SelectedItem = setting.Value,
                        MinWidth = 160,
                        HorizontalAlignment = HorizontalAlignment.Left,
                    };
                    settingRow.Children.Add(choices);
                    var apply = Button("PREVIEW THIS CHANGE");
                    apply.Click += (_, _) =>
                    {
                        try
                        {
                            var updated = GuidedIniEditor.PreviewChange(editor.Text ?? "",
                                setting, choices.SelectedItem?.ToString() ?? setting.Value);
                            editor.Text = updated;
                            _status.Text = "Preview updated. Review the INI and press Save to write with backup.";
                            RenderGuided();
                        }
                        catch (Exception ex) { _status.Text = "Guided edit refused: " + ex.Message; }
                    };
                    settingRow.Children.Add(apply);
                    guidePanel.Children.Add(Panel(settingRow, new Thickness(12)));
                }
            }
            RenderGuided();
            panel.Children.Add(guidePanel);
            panel.Children.Add(Text(UiLanguage.Translate("Raw INI editor").ToUpperInvariant(),
                12, AccentBrush, FontWeight.Bold));
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
                    RenderGuided();
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
            var general = new StackPanel { Spacing = 13 };
            var credits = new StackPanel { Spacing = 12 };
            var updates = new StackPanel { Spacing = 12 };
            var columns = new Grid
            {
                ColumnDefinitions = new ColumnDefinitions("*,*"),
                RowDefinitions = new RowDefinitions("Auto,Auto"),
                ColumnSpacing = 16,
                RowSpacing = 16,
            };
            var leftColumn = new StackPanel { Spacing = 16 };
            leftColumn.Children.Add(Panel(general));
            leftColumn.Children.Add(Panel(credits));
            var rightColumn = new StackPanel { Spacing = 16 };
            rightColumn.Children.Add(Panel(updates));
            columns.Children.Add(leftColumn);
            Grid.SetColumn(rightColumn, 1);
            columns.Children.Add(rightColumn);
            columns.SizeChanged += (_, e) =>
            {
                var compact = e.NewSize.Width < 790;
                columns.ColumnDefinitions[1].Width = compact
                    ? new GridLength(0) : new GridLength(1, GridUnitType.Star);
                Grid.SetColumn(rightColumn, compact ? 0 : 1);
                Grid.SetRow(rightColumn, compact ? 1 : 0);
            };
            panel.Children.Add(columns);
            general.Children.Add(Text("GENERAL / DOWNLOADS",
                12, AccentBrush, FontWeight.Bold));
            var languagePicker = new ComboBox
            {
                ItemsSource = new[] { "English", "Polski" },
                SelectedIndex = UiLanguage.Current == "pl" ? 1 : 0,
                MinWidth = 210,
                HorizontalAlignment = HorizontalAlignment.Left,
            };
            general.Children.Add(Text(UiLanguage.Translate("Language").ToUpperInvariant(),
                12, AccentBrush, FontWeight.Bold));
            general.Children.Add(languagePicker);
            general.Children.Add(Text("Language choice affects launcher navigation, the library and core controls. " +
                "Detailed diagnostics and upstream package names remain in their original language.",
                12, MutedBrush));
            var applyLanguage = Button("APPLY LANGUAGE");
            applyLanguage.Click += (_, _) =>
            {
                try
                {
                    UiLanguage.Set(languagePicker.SelectedIndex == 1 ? "pl" : "en");
                    ApplyLanguage();
                }
                catch (Exception ex) { _status.Text = "Language preference not saved: " + ex.Message; }
            };
            general.Children.Add(applyLanguage);
            general.Children.Add(Text("DEFAULT PROXY DLL", 12, AccentBrush, FontWeight.Bold));
            var aliases = new[] { "dxgi.dll", "version.dll", "winmm.dll", "winhttp.dll",
                "wininet.dll", "dbghelp.dll", "d3d12.dll", "OptiScaler.asi" };
            var choice = new ComboBox
            {
                ItemsSource = aliases,
                SelectedItem = config.DefaultAlias,
                Width = 235,
                HorizontalAlignment = HorizontalAlignment.Left,
            };
            general.Children.Add(choice);
            general.Children.Add(Text("RELEASE DOWNLOAD DIRECTORY", 12, AccentBrush, FontWeight.Bold));
            var download = new TextBox
            {
                Text = config.DownloadDirectory,
                Background = BackgroundBrush,
                Foreground = ForegroundBrush,
                HorizontalAlignment = HorizontalAlignment.Stretch,
            };
            general.Children.Add(download);
            var prerelease = new CheckBox
            {
                Content = "Show prerelease builds in the release picker",
                IsChecked = config.ShowPrereleases,
                Foreground = ForegroundBrush,
            };
            general.Children.Add(prerelease);
            general.Children.Add(Text("Downloads remain manual and checksum-verified. " +
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
            general.Children.Add(save);
            general.Children.Add(Text("GETTING STARTED", 12, AccentBrush, FontWeight.Bold));
            general.Children.Add(Text(
                "The introduction explains the library, user-confirmed setup, recovery and Linux compatibility.",
                12, MutedBrush));
            var introButton = Button("REPLAY INTRODUCTION");
            introButton.Click += async (_, _) => await ShowOnboardingAsync(replay: true);
            general.Children.Add(introButton);
            credits.Children.Add(Text("OPEN SOURCE & ACKNOWLEDGEMENTS",
                12, AccentBrush, FontWeight.Bold));
            credits.Children.Add(Text(
                "Thanks to hassanm0301 and AMDNR-Linux contributors for their public ROCm/HIP " +
                "bridge research and Proton compatibility findings. This project has informed " +
                "our Linux investigation; no AMDNR-Linux code or bridge binaries are " +
                "integrated into this launcher. AMDNR-Linux is licensed GPL-3.0; " +
                "any future code reuse requires license compliance and explicit attribution. " +
                "See Launcher/Avalonia/THIRD_PARTY_ACKNOWLEDGEMENTS.md in our source repository.",
                12, MutedBrush));
            var researchCredits = Button("VIEW AMDNR-LINUX RESEARCH");
            researchCredits.Click += (_, _) =>
            {
                try
                {
                    Process.Start(new ProcessStartInfo
                    {
                        FileName = "https://github.com/hassanm0301/AMDNR-Linux",
                        UseShellExecute = true,
                    });
                }
                catch (Exception ex) { _status.Text = "Could not open credits: " + ex.Message; }
            };
            credits.Children.Add(researchCredits);
            updates.Children.Add(Text("LINUX LAUNCHER UPDATES", 12, AccentBrush, FontWeight.Bold));
            updates.Children.Add(Text(
                "Checks independent Linux launcher releases from your fork. AMDNR game files still " +
                "download exclusively from official upstream. Packages are SHA-256 verified; " +
                "AppImage replacement is opt-in and preserves a previous launcher copy.",
                12, MutedBrush));
            var checkUpdate = Button("CHECK FOR LAUNCHER UPDATES");
            var getUpdate = Button("DOWNLOAD VERIFIED APPIMAGE");
            var applyUpdate = Button("INSTALL DOWNLOADED APPIMAGE");
            getUpdate.IsEnabled = false;
            applyUpdate.IsEnabled = false;
            var updateSummary = Text("No update check performed.", 12, MutedBrush);
            var updateActions = new WrapPanel { ItemSpacing = 10, LineSpacing = 8 };
            updateActions.Children.Add(checkUpdate);
            updateActions.Children.Add(getUpdate);
            updateActions.Children.Add(applyUpdate);
            updates.Children.Add(updateActions);
            updates.Children.Add(updateSummary);
            string? verifiedDownloaded = null;
            checkUpdate.Click += async (_, _) =>
            {
                if (_busy || _backend is null) return;
                _busy = true;
                checkUpdate.IsEnabled = false;
                try
                {
                    var (exit, output) = await _backend.RunAsync(new[]
                        { "--check-launcher-updates" });
                    if (exit != 0) throw new InvalidOperationException(output);
                    using var doc = JsonDocument.Parse(output);
                    var root = doc.RootElement;
                    var available = root.GetProperty("available").GetBoolean();
                    var latest = root.GetProperty("latest");
                    updateSummary.Text = "Installed: " + root.GetProperty("current").GetString() +
                        " · Latest: " + (latest.ValueKind == JsonValueKind.Null
                            ? "No packaged release yet" : latest.GetProperty("tag").GetString()) +
                        (available ? " · Verified update available" : " · No newer release found");
                    getUpdate.IsEnabled = available;
                    applyUpdate.IsEnabled = false;
                    verifiedDownloaded = null;
                }
                catch (Exception ex) { _status.Text = "Launcher update lookup failed: " + ex.Message; }
                finally { _busy = false; checkUpdate.IsEnabled = true; }
            };
            getUpdate.Click += async (_, _) =>
            {
                if (_busy || _backend is null) return;
                _busy = true;
                getUpdate.IsEnabled = false;
                try
                {
                    var (exit, output) = await _backend.RunAsync(new[]
                        { "--download-launcher-update" });
                    if (exit != 0) throw new InvalidOperationException(output);
                    using var doc = JsonDocument.Parse(output);
                    var data = doc.RootElement;
                    if (data.GetProperty("status").GetString() != "downloaded")
                        throw new InvalidOperationException("No newer published package.");
                    verifiedDownloaded = data.GetProperty("file").GetString();
                    updateSummary.Text = "Verified launcher update downloaded: " + verifiedDownloaded +
                        ". Installation only works for a user-owned AppImage.";
                    applyUpdate.IsEnabled = !string.IsNullOrWhiteSpace(verifiedDownloaded);
                }
                catch (Exception ex) { _status.Text = "Verified update download failed: " + ex.Message; }
                finally { _busy = false; getUpdate.IsEnabled = true; }
            };
            applyUpdate.Click += async (_, _) =>
            {
                if (_busy || _backend is null || string.IsNullOrWhiteSpace(verifiedDownloaded)) return;
                _busy = true;
                applyUpdate.IsEnabled = false;
                try
                {
                    var (exit, output) = await _backend.RunAsync(new[]
                        { "--apply-launcher-update", verifiedDownloaded,
                          "--accept-launcher-update" });
                    if (exit != 0) throw new InvalidOperationException(output);
                    updateSummary.Text = "Update applied. Quit and restart the AppImage. " +
                        "Your previous executable was preserved as .amdnr-previous.";
                    _status.Text = "Launcher update applied; restart required.";
                }
                catch (Exception ex) { _status.Text = "Launcher update not applied: " + ex.Message; }
                finally { _busy = false; }
            };
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
