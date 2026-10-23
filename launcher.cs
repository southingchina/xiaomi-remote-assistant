using System;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;

class Launcher {
    [STAThread]
    static void Main(string[] args) {
        string root=AppDomain.CurrentDomain.BaseDirectory;
        string executable=Path.Combine(root,"XiaomiRemoteCore.exe");
        try {
            var start=new ProcessStartInfo(executable);
            start.WorkingDirectory=root;
            start.UseShellExecute=false;
            start.CreateNoWindow=true;
            // Only fixed supported switches are forwarded by this desktop entry.
            start.Arguments=Array.IndexOf(args,"--stop")>=0?"--stop":Array.IndexOf(args,"--tray")>=0?"--tray":"";
            Process.Start(start);
        } catch(Exception e) {
            MessageBox.Show("无法启动小米遥控助手："+e.Message,"小米遥控助手");
        }
    }
}
