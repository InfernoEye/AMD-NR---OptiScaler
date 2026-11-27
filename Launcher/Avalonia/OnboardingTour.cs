using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.Primitives;
using Avalonia.Layout;
using Avalonia.Media;
using Avalonia.Threading;
using System;
using System.IO;

namespace Amdnr.Linux.Desktop;

/// <summary>
/// Control-anchored walkthrough that navigates real pages without mutating game files.
/// </summary>
internal sealed class OnboardingTour
{
    private static readonly IBrush Surface = new SolidColorBrush(Color.Parse("#201E22"));
    private static readonly IBrush Red = new SolidColorBrush(Color.Parse("#C62B43"));
    private static readonly IBrush Light = new SolidColorBrush(Color.Parse("#F4F2F4"));
    private readonly Popup _popup;
    private readonly Func<int, Control> _resolve;
    private readonly Action _finished;
    private readonly Func<bool> _horizontalNavigation;
    private readonly string _seenFile;
    private TemplatedControl? _outlined;
    private IBrush? _previousBrush;
    private Thickness _previousThickness;
    private int _index;
    public bool IsActive { get; private set; }

    private static readonly (string EnTitle, string EnBody, string PlTitle, string PlBody)[] Steps =
    {
        ("Library", "The highlighted Library control takes you back to your actual games.",
            "Biblioteka", "Podświetlony przycisk Biblioteka prowadzi do Twoich prawdziwych gier."),
        ("Grid and List", "These are the actual Grid and List buttons. Grid shows cover cards and side navigation; List moves navigation to the top.",
            "Siatka i lista", "To prawdziwe przyciski Siatka i Lista. Siatka pokazuje okładki i boczną nawigację, a Lista przenosi nawigację na górę."),
        ("Find a game", "This search filters your real library. Select a game card to see details; use Add manually if nothing was detected.",
            "Znajdź grę", "To pole filtruje Twoją bibliotekę. Wybierz kartę gry, aby zobaczyć szczegóły. Jeśli nic nie znaleziono, użyj Dodaj ręcznie."),
        ("Installed games", "This Installed section shows tracked AMDNR installations and verification tools. Viewing it never changes files.",
            "Zainstalowane gry", "Sekcja Zainstalowane zawiera instalacje AMDNR i narzędzia weryfikacji. Samo otwarcie nie zmienia plików."),
        ("Manual installation", "Here you review the Windows executable, official release and DLL proxy. Installing requires explicit approval; Steam settings are not silently changed.",
            "Ręczna instalacja", "Tutaj sprawdzasz plik Windows .exe, oficjalne wydanie i DLL. Instalacja wymaga zgody, a opcje Steam nie są zmieniane po cichu."),
        ("Diagnostics and recovery", "The highlighted Doctor section contains integrity checks and recovery tools. They are never triggered just by viewing this page.",
            "Diagnostyka i odzyskiwanie", "Podświetlona Diagnostyka zawiera kontrole i odzyskiwanie. Samo przeglądanie strony ich nie uruchamia."),
        ("Settings and language", "You are on the real Settings page. Change language, downloads or review credits here.",
            "Ustawienia i język", "To prawdziwa strona Ustawienia. Tutaj zmienisz język, pobieranie i zobaczysz podziękowania."),
        ("Help", "The Help page explains Proton, unsupported runtimes and collecting diagnostics. Replay the tour here any time.",
            "Pomoc", "Strona Pomoc wyjaśnia Protona, ograniczenia i diagnostykę. Możesz tutaj powtórzyć prezentację."),
    };

    public OnboardingTour(Grid shell, Func<int, Control> resolve, Action finished,
        Func<bool> horizontalNavigation, string seenFile)
    {
        _resolve = resolve;
        _finished = finished;
        _horizontalNavigation = horizontalNavigation;
        _seenFile = seenFile;
        _popup = new Popup
        {
            Placement = PlacementMode.Right,
            IsLightDismissEnabled = false,
            HorizontalOffset = 12,
            VerticalOffset = 6,
        };
        Grid.SetRowSpan(_popup, 2);
        shell.Children.Add(_popup);
    }

    public bool HasBeenSeen => File.Exists(_seenFile);

    public void Start()
    {
        _index = 0;
        IsActive = true;
        Dispatcher.UIThread.Post(Render);
    }

    public void Back()
    {
        if (!IsActive) return;
        if (_index == 0) { Close(); return; }
        _index--;
        Render();
    }

    public void Next()
    {
        if (!IsActive) return;
        if (_index == Steps.Length - 1) { Close(); return; }
        _index++;
        Render();
    }

    public void Close(bool markSeen = true)
    {
        _popup.IsOpen = false;
        RestoreOutline();
        if (!IsActive) return;
        IsActive = false;
        if (markSeen)
        {
            try
            {
                Directory.CreateDirectory(Path.GetDirectoryName(_seenFile)!);
                File.WriteAllText(_seenFile, "completed\n");
            }
            catch (IOException) { }
            catch (UnauthorizedAccessException) { }
        }
        _finished();
    }

    private void RestoreOutline()
    {
        if (_outlined is not null)
        {
            _outlined.BorderBrush = _previousBrush;
            _outlined.BorderThickness = _previousThickness;
            _outlined = null;
        }
    }

    private static TextBlock Text(string text, int size, IBrush brush, bool bold = false) => new()
    {
        Text = text, FontSize = size, Foreground = brush,
        FontWeight = bold ? FontWeight.Bold : FontWeight.Normal,
        TextWrapping = TextWrapping.Wrap,
    };

    private void Render()
    {
        if (!IsActive) return;
        _popup.IsOpen = false;
        RestoreOutline();
        var target = _resolve(_index);
        target.BringIntoView();
        if (target is TemplatedControl control)
        {
            _outlined = control;
            _previousBrush = control.BorderBrush;
            _previousThickness = control.BorderThickness;
            control.BorderBrush = Red;
            control.BorderThickness = new Thickness(3);
        }
        var polish = UiLanguage.Current == "pl";
        var current = Steps[_index];
        var bottomAnchor = _index is 1 or 2 || _horizontalNavigation();
        var content = new StackPanel { Width = 328, Spacing = 11 };
        content.Children.Add(Text(bottomAnchor ? "▲" : "◀", 17, Red, true));
        content.Children.Add(Text((polish ? "PREZENTACJA" : "WALKTHROUGH") +
            $"   {_index + 1} / {Steps.Length}", 11, Red, true));
        content.Children.Add(Text(polish ? current.PlTitle : current.EnTitle, 21, Light, true));
        content.Children.Add(Text(polish ? current.PlBody : current.EnBody, 13, Light));
        var actions = new WrapPanel { ItemSpacing = 8, LineSpacing = 8 };
        Button MakeButton(string label, bool primary = false) => new()
        {
            Content = label, Background = primary ? Red : Surface,
            Foreground = Light, Padding = new Thickness(13, 9),
            BorderBrush = Red, BorderThickness = new Thickness(1),
            CornerRadius = new CornerRadius(5),
        };
        var skip = MakeButton(polish ? "POMIŃ" : "SKIP");
        var back = MakeButton(polish ? "WSTECZ" : "BACK");
        var next = MakeButton(_index == Steps.Length - 1
            ? (polish ? "ZAKOŃCZ" : "FINISH") : (polish ? "DALEJ →" : "NEXT →"), true);
        back.IsEnabled = _index > 0;
        skip.Click += (_, _) => Close();
        back.Click += (_, _) => Back();
        next.Click += (_, _) => Next();
        actions.Children.Add(skip);
        actions.Children.Add(back);
        actions.Children.Add(next);
        content.Children.Add(actions);
        _popup.Child = new Border
        {
            Child = content, Background = Surface, BorderBrush = Red,
            BorderThickness = new Thickness(1), CornerRadius = new CornerRadius(9),
            Padding = new Thickness(18),
        };
        _popup.PlacementTarget = target;
        _popup.Placement = bottomAnchor ? PlacementMode.Bottom : PlacementMode.Right;
        Dispatcher.UIThread.Post(() => { if (IsActive) _popup.IsOpen = true; });
    }
}
