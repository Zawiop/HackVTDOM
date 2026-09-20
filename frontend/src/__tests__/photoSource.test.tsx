import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import PhotoSourcePicker, {
  MAX_FILE_BYTES,
  MAX_FILES,
  validateFiles,
} from "../photo/PhotoSourcePicker";

/** A File of a given type and size, without allocating the bytes. */
function fakeFile(name: string, type: string, size = 2048): File {
  const file = new File(["x"], name, { type });
  Object.defineProperty(file, "size", { value: size });
  return file;
}

/** The picker only offers "Take Photo" on a device that has one. */
function setPointer(coarse: boolean) {
  vi.stubGlobal("matchMedia", (q: string) => ({
    matches: q.includes("pointer: coarse") ? coarse : false,
    media: q,
    addEventListener() {},
    removeEventListener() {},
  }));
  Object.defineProperty(navigator, "maxTouchPoints", { value: coarse ? 5 : 0, configurable: true });
}

describe("validateFiles", () => {
  it("accepts ordinary phone and desktop image types", () => {
    const { accepted, rejected } = validateFiles(
      [fakeFile("a.jpg", "image/jpeg"), fakeFile("b.png", "image/png")],
      0,
    );
    expect(accepted).toHaveLength(2);
    expect(rejected).toEqual([]);
  });

  it("accepts an iPhone HEIC that arrives with no MIME type at all", () => {
    // Safari frequently hands over HEIC with an empty `type`; rejecting on
    // that alone would refuse the default format of every recent iPhone.
    const { accepted } = validateFiles([fakeFile("IMG_0431.HEIC", "")], 0);
    expect(accepted).toHaveLength(1);
  });

  it("refuses a video picked from the camera roll", () => {
    const { accepted, rejected } = validateFiles([fakeFile("clip.mov", "video/quicktime")], 0);
    expect(accepted).toEqual([]);
    expect(rejected[0].reason).toMatch(/not an image/);
  });

  it("refuses a disguised executable", () => {
    const { rejected } = validateFiles([fakeFile("payload.exe", "application/x-msdownload")], 0);
    expect(rejected[0].reason).toMatch(/not an image/);
  });

  it("refuses an empty file and one over the size cap", () => {
    const { rejected } = validateFiles(
      [fakeFile("empty.jpg", "image/jpeg", 0), fakeFile("huge.jpg", "image/jpeg", MAX_FILE_BYTES + 1)],
      0,
    );
    expect(rejected.map((r) => r.reason)).toEqual([
      expect.stringMatching(/empty/),
      expect.stringMatching(/too large/),
    ]);
  });

  it("counts files already chosen against the limit", () => {
    const batch = Array.from({ length: 3 }, (_, i) => fakeFile(`p${i}.jpg`, "image/jpeg"));
    const { accepted, rejected } = validateFiles(batch, MAX_FILES - 1);
    expect(accepted).toHaveLength(1);
    expect(rejected).toHaveLength(2);
    expect(rejected[0].reason).toMatch(/limit/);
  });
});

describe("PhotoSourcePicker", () => {
  it("offers camera, library and file on a phone", () => {
    setPointer(true);
    render(<PhotoSourcePicker value={[]} onChange={vi.fn()} />);

    expect(screen.getByRole("button", { name: /take photo/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /choose photo/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /upload file/i })).toBeInTheDocument();
  });

  it("hides Take Photo where there is no camera to open", () => {
    setPointer(false);
    render(<PhotoSourcePicker value={[]} onChange={vi.fn()} />);

    expect(screen.queryByRole("button", { name: /take photo/i })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /choose image/i })).toBeInTheDocument();
  });

  it("puts capture on the camera input and NOWHERE else", () => {
    setPointer(true);
    render(<PhotoSourcePicker value={[]} onChange={vi.fn()} />);

    const camera = screen.getByTestId("photo-camera-input");
    const library = screen.getByTestId("photo-library-input");
    const file = screen.getByTestId("photo-file-input");

    // This is the whole mechanism: `capture` is what opens the camera on iOS
    // and Android, and putting it on the library input would skip past the
    // photo roll entirely.
    expect(camera).toHaveAttribute("capture", "environment");
    expect(camera).toHaveAttribute("accept", "image/*");
    expect(library).not.toHaveAttribute("capture");
    expect(file).not.toHaveAttribute("capture");
  });

  it("lets the library and file routes take several photos, the camera one", () => {
    setPointer(true);
    render(<PhotoSourcePicker value={[]} onChange={vi.fn()} />);

    expect(screen.getByTestId("photo-camera-input")).not.toHaveAttribute("multiple");
    expect(screen.getByTestId("photo-library-input")).toHaveAttribute("multiple");
    expect(screen.getByTestId("photo-file-input")).toHaveAttribute("multiple");
  });

  it("appends a new pick to what is already chosen", async () => {
    setPointer(true);
    const onChange = vi.fn();
    const existing = [fakeFile("front.jpg", "image/jpeg")];

    render(<PhotoSourcePicker value={existing} onChange={onChange} />);
    await userEvent.upload(screen.getByTestId("photo-library-input"), fakeFile("side.jpg", "image/jpeg"));

    expect(onChange).toHaveBeenCalledWith([
      expect.objectContaining({ name: "front.jpg" }),
      expect.objectContaining({ name: "side.jpg" }),
    ]);
  });

  it("shows why a file was refused rather than dropping it silently", async () => {
    setPointer(true);
    render(<PhotoSourcePicker value={[]} onChange={vi.fn()} />);

    // `applyAccept: false` reproduces the case the validation exists for: the
    // `accept` attribute is a hint, and some Android file managers hand back
    // whatever the user picked regardless of it.
    await userEvent.upload(
      screen.getByTestId("photo-file-input"),
      fakeFile("notes.txt", "text/plain"),
      { applyAccept: false },
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(/not an image/i);
  });

  it("the accept attribute still narrows the picker in the normal case", async () => {
    setPointer(true);
    const onChange = vi.fn();
    render(<PhotoSourcePicker value={[]} onChange={onChange} />);

    await userEvent.upload(
      screen.getByTestId("photo-file-input"),
      fakeFile("notes.txt", "text/plain"),
    );

    expect(onChange).not.toHaveBeenCalled();
  });

  it("marks the first photo as the front, which is the one that gets redesigned", () => {
    setPointer(true);
    render(
      <PhotoSourcePicker
        value={[fakeFile("a.jpg", "image/jpeg"), fakeFile("b.jpg", "image/jpeg")]}
        onChange={vi.fn()}
      />,
    );

    const tags = screen.getAllByText("front");
    expect(tags).toHaveLength(1);
  });

  it("disables every route while a generation is running", () => {
    setPointer(true);
    render(<PhotoSourcePicker value={[]} onChange={vi.fn()} disabled />);

    for (const name of [/take photo/i, /choose photo/i, /upload file/i]) {
      expect(screen.getByRole("button", { name })).toBeDisabled();
    }
  });
});
