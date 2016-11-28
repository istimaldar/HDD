import os
import tkinter as tk
from tkinter import ttk
import atapt

class MainWindow(tk.Tk):
    def __init__(self):
        tk.Tk.__init__(self)

        self.table = ttk.Treeview()
        self.table["columns"] = ("#1", "#2", "#3", "#4", "#5", "#6", "#7", "#8")
        self.table.heading("#0", text="Название устройства")
        self.table.heading("#1", text="Модель устройства")
        self.table.heading("#2", text="Версия прошивки")
        self.table.heading("#3", text="Серийный номер")
        self.table.heading("#4", text="Всего места")
        self.table.heading("#5", text="Свободно")
        self.table.heading("#6", text="Занято")
        self.table.heading("#7", text="Поддерживаемые стандарты ATA")
        self.table.heading("#8", text="Поддерживаемые модели памяти")
        devices = []
        for device in os.listdir("/sys/block/"):
            if "sd" in device:
                devices.append(device)
        mount_points = {string.split()[0]: string.split()[1].replace("\\040", " ") for string in open('/proc/mounts')}
        for device in sorted(devices):
            device_ata = atapt.atapt('/dev/{}'.format(device))
            try:
                device_ata.checkSense()
            except atapt.senseError:
                continue
            free = 0
            total = 0
            for partition in os.listdir("/sys/block/{}/".format(device)):
                if device in partition:
                    try:
                        stat = os.statvfs(mount_points['/dev/{}'.format(partition)])
                        free += stat.f_bfree * stat.f_bsize
                        total += stat.f_blocks * stat.f_bsize
                    except KeyError:
                        pass
            self.table.insert("", tk.END, text=device,
                              values=(device_ata.model,
                              device_ata.firmware,
                              device_ata.serial,
                              total, free, total-free, " ".join(device_ata.ata_support),
                              " ".join(device_ata.mem_support)))

        self.table.pack(expand=tk.TRUE, fill=tk.BOTH)

        self.mainloop()


if __name__ == "__main__":
    MainWindow()
