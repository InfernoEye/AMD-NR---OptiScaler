using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;

namespace Amdnr.Linux.Desktop;

/// <summary>Adapter to the independent, tested Linux installation manager.</summary>
public sealed class Backend
{
    private readonly string _script;

    public Backend()
    {
        var overridePath = Environment.GetEnvironmentVariable("AMDNR_LINUX_BACKEND");
        var candidates = new[]
        {
            overridePath,
            Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "../../../../amdnr_linux_launcher.py")),
            Path.GetFullPath(Path.Combine(Environment.CurrentDirectory, "linux/amdnr_linux_launcher.py")),
            Path.GetFullPath(Path.Combine(Environment.CurrentDirectory, "../amdnr_linux_launcher.py")),
        };
        _script = candidates.FirstOrDefault(p => !string.IsNullOrEmpty(p) && File.Exists(p))
            ?? throw new FileNotFoundException(
                "Linux installer backend not found. Run from repository root or set AMDNR_LINUX_BACKEND.");
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
        var result = await RunAsync(new[] { "--list" }, token);
        if (result.ExitCode != 0)
            throw new InvalidOperationException(result.Output);
        var games = new List<GameEntry>();
        foreach (var line in result.Output.Split('\n', StringSplitOptions.RemoveEmptyEntries))
        {
            var fields = line.TrimEnd('\r').Split('\t', 2);
            if (fields.Length == 2 && Directory.Exists(fields[1]))
                games.Add(new GameEntry(fields[0], fields[1]));
        }
        return games;
    }
}

public sealed record GameEntry(string Name, string Folder);
