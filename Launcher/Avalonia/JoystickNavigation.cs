using System;
using System.IO;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;

namespace Amdnr.Linux.Desktop;

/// <summary>
/// Optional Linux joydev input for common Steam Deck/gamepad layouts.
/// No root access, system packages, Steam configuration changes, or extra
/// dependencies. Devices that do not expose /dev/input/js* remain keyboard-only.
/// Device-specific button mappings still need hardware testing.
/// </summary>
internal sealed class JoystickNavigation : IDisposable
{
    internal enum Action { Up, Down, Left, Right, Confirm, Back }
    private readonly System.Action<Action> _send;
    private readonly CancellationTokenSource _stop = new();
    private readonly Task _reader;
    private readonly bool[] _axisEngaged = new bool[8];
    private readonly long[] _lastAction = new long[6];

    public JoystickNavigation(System.Action<Action> send)
    {
        _send = send;
        _reader = Task.Run(ReadLoopAsync);
    }

    private void Dispatch(Action action)
    {
        var now = Environment.TickCount64;
        var index = (int)action;
        if (now - Interlocked.Read(ref _lastAction[index]) < 160)
            return;
        Interlocked.Exchange(ref _lastAction[index], now);
        _send(action);
    }

    private void HandleEvent(byte type, byte number, short value)
    {
        // Linux js_event: button=1, axis=2, init flag=0x80.
        // Ignore initialization reports, which are not user interaction.
        if ((type & 0x80) != 0)
            return;
        type &= 0x7f;
        if (type == 1 && value != 0)
        {
            if (number == 0) Dispatch(Action.Confirm);
            else if (number == 1) Dispatch(Action.Back);
            return;
        }
        if (type != 2 || number >= _axisEngaged.Length)
            return;
        // Common layouts: left stick X/Y = 0/1; D-pad hat = 6/7.
        if (number != 0 && number != 1 && number != 6 && number != 7)
            return;
        if (Math.Abs((int)value) < 12000)
        {
            _axisEngaged[number] = false;
            return;
        }
        if (Math.Abs((int)value) < 21000 || _axisEngaged[number])
            return;
        _axisEngaged[number] = true;
        var horizontal = number == 0 || number == 6;
        Dispatch(horizontal
            ? (value > 0 ? Action.Right : Action.Left)
            : (value > 0 ? Action.Down : Action.Up));
    }

    private async Task ReadLoopAsync()
    {
        while (!_stop.IsCancellationRequested)
        {
            var device = Enumerable.Range(0, 8)
                .Select(n => $"/dev/input/js{n}").FirstOrDefault(File.Exists);
            if (device is null)
            {
                try { await Task.Delay(1500, _stop.Token); }
                catch (OperationCanceledException) { break; }
                continue;
            }
            try
            {
                using var input = new FileStream(device, FileMode.Open, FileAccess.Read,
                    FileShare.ReadWrite, 4096, FileOptions.Asynchronous);
                var packet = new byte[8];
                while (!_stop.IsCancellationRequested)
                {
                    var offset = 0;
                    while (offset < packet.Length)
                    {
                        var count = await input.ReadAsync(packet.AsMemory(offset), _stop.Token);
                        if (count == 0) throw new EndOfStreamException();
                        offset += count;
                    }
                    HandleEvent(packet[6], packet[7], BitConverter.ToInt16(packet, 4));
                }
            }
            catch (OperationCanceledException) { break; }
            catch (IOException) { /* Hot-unplugged or inaccessible device. */ }
            catch (UnauthorizedAccessException) { /* User should not need root. */ }
            Array.Clear(_axisEngaged);
            try { await Task.Delay(1500, _stop.Token); }
            catch (OperationCanceledException) { break; }
        }
    }

    public void Dispose()
    {
        _stop.Cancel();
        // Don't block the UI thread waiting for an input device.
        _stop.Dispose();
    }
}
