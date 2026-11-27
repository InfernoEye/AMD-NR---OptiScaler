using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.RegularExpressions;

namespace Amdnr.Linux.Desktop;

/// <summary>
/// Non-destructive UI adapter for a small allow-list of existing INI keys.
/// Never inserts unknown keys, never guesses a runtime, and never saves to disk.
/// The existing Backend.SaveIniAsync performs the explicit backup/hash check.
/// </summary>
internal static class GuidedIniEditor
{
    internal sealed record Entry(string Section, string Key, string Value,
        string Description, IReadOnlyList<string> Choices);

    private sealed record Definition(string Key, string Description, string[] Choices);

    private static readonly Definition[] Known =
    {
        new("AmdLmxxfFastMode", "lmxxf: use a smaller/faster neural network where supported.",
            new[] { "true", "false" }),
        new("AmdLmxxfL37", "lmxxf: choose the optional older optimized model, if supported by this AMDNR package.",
            new[] { "true", "false" }),
        new("AmdPlacement", "Neural pass placement: pre-upscale or post-upscale, if supported.",
            new[] { "pre", "post" }),
        new("AmdFaceDetail", "Face-detail refinement, if supported by the selected runtime.",
            new[] { "true", "false" }),
    };

    private static readonly Regex Header = new(
        @"^\s*\[([^\]]+)\]\s*(?:[;#].*)?$", RegexOptions.Compiled);
    private static readonly Regex Assignment = new(
        @"^(?<prefix>\s*(?<key>[A-Za-z][A-Za-z0-9_]*)\s*=\s*)(?<value>[^;#]*?)(?<suffix>\s*(?:[;#].*)?)$",
        RegexOptions.Compiled);

    internal static IReadOnlyList<Entry> Read(string document)
    {
        var found = new Dictionary<string, Entry>(StringComparer.OrdinalIgnoreCase);
        var duplicate = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        string section = "";
        foreach (var line in document.Split('\n'))
        {
            var clean = line.TrimEnd('\r');
            var heading = Header.Match(clean);
            if (heading.Success)
            {
                section = heading.Groups[1].Value.Trim();
                continue;
            }
            if (!section.Equals("DlssNr", StringComparison.OrdinalIgnoreCase))
                continue;
            var parsed = Assignment.Match(clean);
            if (!parsed.Success) continue;
            var key = parsed.Groups["key"].Value;
            var known = Known.FirstOrDefault(x =>
                x.Key.Equals(key, StringComparison.OrdinalIgnoreCase));
            if (known is null) continue;
            var value = parsed.Groups["value"].Value.Trim();
            if (!known.Choices.Contains(value, StringComparer.OrdinalIgnoreCase))
                continue;
            if (found.ContainsKey(key))
            {
                duplicate.Add(key);
                continue;
            }
            found[key] = new Entry(section, known.Key, value,
                known.Description, known.Choices);
        }
        foreach (var key in duplicate) found.Remove(key);
        return Known.Where(x => found.ContainsKey(x.Key)).Select(x => found[x.Key]).ToList();
    }

    internal static string PreviewChange(string document, Entry selected, string newValue)
    {
        if (!selected.Choices.Contains(newValue, StringComparer.OrdinalIgnoreCase))
            throw new ArgumentException("Unsupported setting value.", nameof(newValue));
        var existing = Read(document)
            .SingleOrDefault(e => e.Key.Equals(selected.Key, StringComparison.OrdinalIgnoreCase));
        if (existing is null || !existing.Value.Equals(selected.Value, StringComparison.OrdinalIgnoreCase))
            throw new InvalidOperationException("The selected setting changed; reload the guided controls.");

        var separator = document.Contains("\r\n", StringComparison.Ordinal) ? "\r\n" : "\n";
        var lines = document.Split(new[] { separator }, StringSplitOptions.None);
        string section = "";
        int replacements = 0;
        for (int i = 0; i < lines.Length; i++)
        {
            var heading = Header.Match(lines[i]);
            if (heading.Success)
            {
                section = heading.Groups[1].Value.Trim();
                continue;
            }
            if (!section.Equals(selected.Section, StringComparison.OrdinalIgnoreCase))
                continue;
            var match = Assignment.Match(lines[i]);
            if (!match.Success ||
                !match.Groups["key"].Value.Equals(selected.Key, StringComparison.OrdinalIgnoreCase))
                continue;
            lines[i] = match.Groups["prefix"].Value + newValue + match.Groups["suffix"].Value;
            replacements++;
        }
        if (replacements != 1)
            throw new InvalidOperationException("Ambiguous setting; use the raw INI editor.");
        return string.Join(separator, lines);
    }
}
