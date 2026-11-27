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

    public async Task<IReadOnlyList<ExecutableEntry>> ExecutablesAsync(
        string gameFolder, CancellationToken token = default)
    {
        var (exit, output) = await RunAsync(new[] { "--exes-json", gameFolder }, token);
        if (exit != 0) throw new InvalidOperationException(output);
        using var document = JsonDocument.Parse(output);
        var results = new List<ExecutableEntry>();
        foreach (var item in document.RootElement.EnumerateArray())
        {
            var path = item.GetProperty("path").GetString();
            if (string.IsNullOrWhiteSpace(path) || !File.Exists(path)) continue;
            results.Add(new ExecutableEntry(path,
                item.GetProperty("recommended").GetBoolean(),
                item.GetProperty("suspicious").GetBoolean(),
                item.GetProperty("auto_select").GetBoolean()));
        }
        return results;
    }

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

public sealed record GameEntry(string Name, string Folder, string? Artwork);

public sealed record ExecutableEntry(string Path, bool Recommended, bool Suspicious, bool AutoSelect)
{
    public override string ToString() =>
        (Recommended ? "★  " : Suspicious ? "⚠  " : "") + Path;
}


public sealed record ReleaseEntry(string Tag, string Name, string Asset, long Bytes, bool Prerelease)
{
    public override string ToString() => $"{Name}  ·  {Asset}  ({Bytes / (1024.0 * 1024):F0} MiB){(Prerelease ? " · prerelease" : "")}";
}

