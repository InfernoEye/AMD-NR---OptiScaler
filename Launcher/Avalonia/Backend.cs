using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;

namespace Amdnr.Linux.Desktop;

/// <summary>Adapter to the independent, tested Linux installation manager.</summary>
public sealed class Backend
{
    private readonly string _script;

    public Backend()
    {
        var overridePath = Environment.GetEnvironmentVariable("AMDNR_AVALONIA_BACKEND")
            ?? Environment.GetEnvironmentVariable("AMDNR_LINUX_BACKEND");
        var candidates = new[]
        {
            overridePath,
            Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "../../../amdnr_launcher.py")),
            Path.GetFullPath(Path.Combine(Environment.CurrentDirectory, "Launcher/Avalonia/amdnr_launcher.py")),
            Path.GetFullPath(Path.Combine(Environment.CurrentDirectory, "amdnr_launcher.py")),
        };
        _script = candidates.FirstOrDefault(p => !string.IsNullOrEmpty(p) && File.Exists(p))
            ?? throw new FileNotFoundException(
                "Linux installer backend not found. Run from repository root or set AMDNR_AVALONIA_BACKEND.");
    }

    public async Task<(int ExitCode, string Output)> RunAsync(
        IEnumerable<string> arguments, CancellationToken token = default)
    {
        using var process = new Process();
        process.StartInfo = new ProcessStartInfo
        {
            FileName = "python3",
            UseShellExecute = false,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            CreateNoWindow = true,
        };
        process.StartInfo.ArgumentList.Add(_script);
        foreach (var argument in arguments)
            process.StartInfo.ArgumentList.Add(argument);
        process.Start();
        var output = process.StandardOutput.ReadToEndAsync(token);
        var errors = process.StandardError.ReadToEndAsync(token);
        await process.WaitForExitAsync(token);
        var text = await output;
        var errorText = await errors;
        return (process.ExitCode, string.IsNullOrWhiteSpace(errorText)
            ? text.Trim() : (text + Environment.NewLine + errorText).Trim());
    }

    public async Task<IReadOnlyList<IndexedGameEntry>> DifferentialGamesAsync(
        CancellationToken token = default)
    {
        var (exit, output) = await RunAsync(new[] { "--library-differential-json" }, token);
        if (exit != 0) throw new InvalidOperationException(output);
        using var document = JsonDocument.Parse(output);
        var games = new List<IndexedGameEntry>();
        foreach (var item in document.RootElement.EnumerateArray())
        {
            var name = item.GetProperty("name").GetString();
            var folder = item.GetProperty("folder").GetString();
            if (string.IsNullOrWhiteSpace(name) || string.IsNullOrWhiteSpace(folder))
                continue;
            var artwork = item.TryGetProperty("artwork", out var art) &&
                art.ValueKind == JsonValueKind.String ? art.GetString() : null;
            var executable = item.TryGetProperty("executable", out var exe) &&
                exe.ValueKind == JsonValueKind.String ? exe.GetString() : null;
            games.Add(new IndexedGameEntry(
                new GameEntry(name, folder,
                    artwork is not null && File.Exists(artwork) ? artwork : null,
                    item.GetProperty("custom").GetBoolean()),
                executable is not null && File.Exists(executable) ? executable : null));
        }
        return games;
    }

    public async Task IndexLibraryExecutableAsync(string folder, string executable,
        CancellationToken token = default)
    {
        var (exit, output) = await RunAsync(
            new[] { "--library-index-exe", folder, "--exe", executable }, token);
        if (exit != 0) throw new InvalidOperationException(output);
    }

    public async Task<IReadOnlyList<GameEntry>> GamesAsync(CancellationToken token = default)
    {
        var result = await RunAsync(new[] { "--list-json", "--download-artwork" }, token);
        if (result.ExitCode != 0)
            throw new InvalidOperationException(result.Output);
        using var document = JsonDocument.Parse(result.Output);
        var games = new List<GameEntry>();
        foreach (var item in document.RootElement.EnumerateArray())
        {
            var name = item.GetProperty("name").GetString();
            var folder = item.GetProperty("folder").GetString();
            if (string.IsNullOrWhiteSpace(name) || string.IsNullOrWhiteSpace(folder)
                || !Directory.Exists(folder))
                continue;
            var artwork = item.GetProperty("artwork").GetString();
            games.Add(new GameEntry(name, folder,
                artwork is not null && File.Exists(artwork) ? artwork : null));
        }
        return games;
    }

    public async Task<IReadOnlyList<GameEntry>> CustomGamesAsync()
    {
        var (exit, output) = await RunAsync(new[] { "--custom-games-json" });
        if (exit != 0) throw new InvalidOperationException(output);
        using var document = JsonDocument.Parse(output);
        var games = new List<GameEntry>();
        foreach (var item in document.RootElement.EnumerateArray())
        {
            var name = item.GetProperty("name").GetString();
            var folder = item.GetProperty("folder").GetString();
            if (string.IsNullOrWhiteSpace(name) || string.IsNullOrWhiteSpace(folder))
                continue;
            var artwork = item.GetProperty("artwork").GetString();
            games.Add(new GameEntry(name, folder,
                artwork is not null && File.Exists(artwork) ? artwork : null, true));
        }
        return games;
    }

    public async Task AddCustomGameAsync(string folder, string name)
    {
        var (exit, output) = await RunAsync(new[] {
            "--add-custom-game", folder, "--custom-name", name
        });
        if (exit != 0) throw new InvalidOperationException(output);
    }

    public async Task RenameCustomGameAsync(string folder, string name)
    {
        var (exit, output) = await RunAsync(new[] {
            "--rename-custom-game", folder, "--custom-name", name
        });
        if (exit != 0) throw new InvalidOperationException(output);
    }

    public async Task RemoveCustomGameAsync(string folder)
    {
        var (exit, output) = await RunAsync(new[] {
            "--remove-custom-game", folder
        });
        if (exit != 0) throw new InvalidOperationException(output);
    }

    public async Task<InstallationReport> InstallationAsync(string executable)
    {
        var (exit, output) = await RunAsync(new[] { "--installation-json", "--exe", executable });
        if (exit != 0) throw new InvalidOperationException(output);
        using var document = JsonDocument.Parse(output);
        var record = document.RootElement;
        string? ReadString(string name) =>
            record.TryGetProperty(name, out var item) && item.ValueKind == JsonValueKind.String
                ? item.GetString() : null;
        int ReadInt(string name) => record.TryGetProperty(name, out var item) &&
            item.ValueKind == JsonValueKind.Number ? item.GetInt32() : 0;
        return new InstallationReport(
            record.GetProperty("installed").GetBoolean(), ReadString("status") ?? "unknown",
            ReadString("alias"), ReadString("source_archive"), ReadString("source_sha256"),
            ReadInt("files"), ReadInt("verified"), ReadInt("missing"), ReadInt("modified"),
            ReadInt("backups_missing"), ReadString("error"));
    }

    public async Task<string?> SavedExecutableAsync(string folder)
    {
        var (exit, output) = await RunAsync(new[] { "--saved-exe", folder });
        if (exit != 0) throw new InvalidOperationException(output);
        return string.IsNullOrWhiteSpace(output) ? null : output;
    }

    public async Task RememberExecutableAsync(string folder, string executable)
    {
        var (exit, output) = await RunAsync(new[]
            { "--remember-exe", folder, "--exe", executable });
        if (exit != 0) throw new InvalidOperationException(output);
    }

    public async Task<ExecutableScan> ScanExecutablesAsync(
        string gameFolder, CancellationToken token = default)
    {
        var (exit, output) = await RunAsync(new[] { "--exe-scan-json", gameFolder }, token);
        if (exit != 0) throw new InvalidOperationException(output);
        using var document = JsonDocument.Parse(output);
        var root = document.RootElement;
        var results = new List<ExecutableEntry>();
        foreach (var item in root.GetProperty("candidates").EnumerateArray())
        {
            var path = item.GetProperty("path").GetString();
            if (string.IsNullOrWhiteSpace(path) || !File.Exists(path)) continue;
            results.Add(new ExecutableEntry(path,
                item.GetProperty("recommended").GetBoolean(),
                item.GetProperty("suspicious").GetBoolean(),
                item.GetProperty("auto_select").GetBoolean()));
        }
        var native = root.GetProperty("native").EnumerateArray()
            .Select(x => x.GetString() ?? "").Where(x => x.Length > 0).ToArray();
        var steam = root.TryGetProperty("steam_launch", out var launch)
            && launch.ValueKind == JsonValueKind.Object ? launch : default;
        var preferred = steam.ValueKind == JsonValueKind.Object &&
            steam.TryGetProperty("selected", out var target) &&
            target.ValueKind == JsonValueKind.String ? target.GetString() : null;
        var steamReason = steam.ValueKind == JsonValueKind.Object &&
            steam.TryGetProperty("reason", out var cause) &&
            cause.ValueKind == JsonValueKind.String ? cause.GetString() : null;
        var missingWindows = steam.ValueKind == JsonValueKind.Object &&
            steam.TryGetProperty("windows_missing", out var missing) &&
            missing.ValueKind == JsonValueKind.Array
            ? missing.EnumerateArray().Where(x => x.ValueKind == JsonValueKind.String)
                .Select(x => x.GetString() ?? "").Where(x => x.Length > 0).ToArray()
            : Array.Empty<string>();
        return new ExecutableScan(results, native,
            root.GetProperty("reason").GetString() ?? "unknown",
            root.GetProperty("partial").GetBoolean(), preferred, steamReason,
            missingWindows);
    }

    public Task<IReadOnlyList<LibraryAuditEntry>> AuditLibraryAsync(
        CancellationToken token = default)
        => ReadLibraryAuditAsync("--library-audit-json", token);

    public Task<IReadOnlyList<LibraryAuditEntry>> SavedLibraryAuditAsync(
        CancellationToken token = default)
        => ReadLibraryAuditAsync("--library-audit-cache-json", token);

    private async Task<IReadOnlyList<LibraryAuditEntry>> ReadLibraryAuditAsync(
        string command, CancellationToken token)
    {
        var (exit, output) = await RunAsync(new[] { command }, token);
        if (exit != 0) throw new InvalidOperationException(output);
        using var document = JsonDocument.Parse(output);
        var entries = new List<LibraryAuditEntry>();
        foreach (var item in document.RootElement.EnumerateArray())
        {
            var folder = item.GetProperty("folder").GetString();
            if (string.IsNullOrWhiteSpace(folder)) continue;
            entries.Add(new LibraryAuditEntry(
                folder,
                item.GetProperty("status").GetString() ?? "scan_error",
                item.TryGetProperty("executable", out var exe) &&
                    exe.ValueKind == JsonValueKind.String ? exe.GetString() : null,
                item.GetProperty("installed_record").GetBoolean(),
                item.GetProperty("custom").GetBoolean(),
                item.TryGetProperty("source", out var source) &&
                    source.ValueKind == JsonValueKind.String ? source.GetString() : null));
        }
        return entries;
    }

    public async Task<IReadOnlyList<ExecutableEntry>> ExecutablesAsync(
        string gameFolder, CancellationToken token = default)
        => (await ScanExecutablesAsync(gameFolder, token)).Candidates;

    public async Task<IReadOnlyList<ReleaseEntry>> ReleasesAsync(CancellationToken token = default)
    {
        var (exit, output) = await RunAsync(new[] { "--releases-json" }, token);
        if (exit != 0) throw new InvalidOperationException(output);
        using var document = JsonDocument.Parse(output);
        var releases = new List<ReleaseEntry>();
        foreach (var item in document.RootElement.EnumerateArray())
        {
            releases.Add(new ReleaseEntry(
                item.GetProperty("tag").GetString() ?? "",
                item.GetProperty("name").GetString() ?? "",
                item.GetProperty("asset").GetString() ?? "",
                item.GetProperty("bytes").GetInt64(),
                item.GetProperty("prerelease").GetBoolean()));
        }
        return releases;
    }

}

public sealed record GameEntry(string Name, string Folder, string? Artwork, bool Custom = false);

public sealed record IndexedGameEntry(GameEntry Game, string? Executable);

public sealed record LibraryAuditEntry(string Folder, string Status, string? Executable,
    bool InstalledRecord, bool Custom, string? Source);

public sealed record InstallationReport(bool Installed, string Status, string? Alias,
    string? SourceArchive, string? SourceSha256, int Files, int Verified,
    int Missing, int Modified, int BackupsMissing, string? Error);


public sealed record ExecutableScan(IReadOnlyList<ExecutableEntry> Candidates,
    IReadOnlyList<string> NativeFiles, string Reason, bool Partial,
    string? SteamPreferred, string? SteamReason,
    IReadOnlyList<string> SteamMissingWindows);

public sealed record ExecutableEntry(string Path, bool Recommended, bool Suspicious, bool AutoSelect)
{
    public override string ToString() =>
        (Recommended ? "★  " : Suspicious ? "⚠  " : "") + Path;
}


public sealed record ReleaseEntry(string Tag, string Name, string Asset, long Bytes, bool Prerelease)
{
    public override string ToString() => $"{Name}  ·  {Asset}  ({Bytes / (1024.0 * 1024):F0} MiB){(Prerelease ? " · prerelease" : "")}";
}

