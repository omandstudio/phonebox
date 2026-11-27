import Foundation
import ScreenCaptureKit
import AVFoundation
import CoreMedia
import CoreGraphics

class AudioCaptureOutput: NSObject, SCStreamOutput {
    let writeQueue = DispatchQueue(label: "audio.write")
    let stdout = FileHandle.standardOutput
    var lastAudioTime = Date.distantPast
    var timer: DispatchSourceTimer?
    var loggedAudio = false
    // 20ms of 48kHz stereo Int16 = 960 frames * 2 channels * 2 bytes = 3840 bytes
    let silenceChunk = Data(count: 960 * 2 * MemoryLayout<Int16>.size)

    func startKeepAlive() {
        let t = DispatchSource.makeTimerSource(queue: writeQueue)
        t.schedule(deadline: .now() + 0.02, repeating: 0.02)
        t.setEventHandler { [weak self] in
            guard let self = self else { return }
            if Date().timeIntervalSince(self.lastAudioTime) > 0.04 {
                do {
                    try self.stdout.write(contentsOf: self.silenceChunk)
                } catch {
                    exit(0)
                }
            }
        }
        t.resume()
        self.timer = t
    }

    func stream(_ stream: SCStream, didOutputSampleBuffer sampleBuffer: CMSampleBuffer, of type: SCStreamOutputType) {
        guard type == .audio else { return }
        guard CMSampleBufferDataIsReady(sampleBuffer) else { return }

        guard let formatDesc = CMSampleBufferGetFormatDescription(sampleBuffer),
              let asbdPtr = CMAudioFormatDescriptionGetStreamBasicDescription(formatDesc) else { return }
        let asbd = asbdPtr.pointee

        let numFrames = CMSampleBufferGetNumSamples(sampleBuffer)
        if numFrames <= 0 { return }
        guard let blockBuf = CMSampleBufferGetDataBuffer(sampleBuffer) else { return }
        let dataLen = CMBlockBufferGetDataLength(blockBuf)
        if dataLen <= 0 { return }

        let channels = max(1, Int(asbd.mChannelsPerFrame))
        let isFloat = (asbd.mFormatFlags & kAudioFormatFlagIsFloat) != 0
        let isNonInterleaved = (asbd.mFormatFlags & kAudioFormatFlagIsNonInterleaved) != 0

        var srcBytes = [UInt8](repeating: 0, count: dataLen)
        let copyStatus = srcBytes.withUnsafeMutableBytes { ptr -> OSStatus in
            guard let base = ptr.baseAddress else { return -1 }
            return CMBlockBufferCopyDataBytes(blockBuf, atOffset: 0, dataLength: dataLen, destination: base)
        }
        if !loggedAudio {
            loggedAudio = true
            fputs("AUDIO_DEBUG copyStatus=\(copyStatus) dataLen=\(dataLen) flags=\(asbd.mFormatFlags) ch=\(channels) frames=\(numFrames)\n", stderr)
            fflush(stderr)
        }
        guard copyStatus == kCMBlockBufferNoErr else { return }

        var outData = Data(count: numFrames * 2 * MemoryLayout<Int16>.size)
        outData.withUnsafeMutableBytes { outRaw in
            guard let outSamples = outRaw.bindMemory(to: Int16.self).baseAddress else { return }
            srcBytes.withUnsafeBytes { inRaw in
                if isFloat {
                    let floats = inRaw.bindMemory(to: Float.self)
                    let totalFloats = floats.count
                    if isNonInterleaved && channels >= 2 && totalFloats >= numFrames * 2 {
                        for i in 0..<numFrames {
                            let l = max(-1.0, min(1.0, floats[i]))
                            let r = max(-1.0, min(1.0, floats[numFrames + i]))
                            outSamples[i * 2] = Int16(l * 32767.0)
                            outSamples[i * 2 + 1] = Int16(r * 32767.0)
                        }
                    } else if totalFloats >= numFrames * channels {
                        for i in 0..<numFrames {
                            let l = max(-1.0, min(1.0, floats[i * channels]))
                            let r = channels >= 2 ? max(-1.0, min(1.0, floats[i * channels + 1])) : l
                            outSamples[i * 2] = Int16(l * 32767.0)
                            outSamples[i * 2 + 1] = Int16(r * 32767.0)
                        }
                    }
                } else {
                    let ints = inRaw.bindMemory(to: Int16.self)
                    if ints.count >= numFrames * channels {
                        for i in 0..<numFrames {
                            outSamples[i * 2] = ints[i * channels]
                            outSamples[i * 2 + 1] = channels >= 2 ? ints[i * channels + 1] : ints[i * channels]
                        }
                    }
                }
            }
        }

        writeQueue.async {
            self.lastAudioTime = Date()
            do {
                try self.stdout.write(contentsOf: outData)
            } catch {
                exit(0)
            }
        }
    }
}

@main
struct MacAudioCapture {
    static var stream: SCStream?
    static let captureOutput = AudioCaptureOutput()

    static func main() async {
        if !CGPreflightScreenCaptureAccess() {
            let _ = CGRequestScreenCaptureAccess()
            fputs("ERROR_PERMISSION: Screen Recording permission required. Grant permission in System Settings > Privacy & Security > Screen Recording.\n", stderr)
            fflush(stderr)
            exit(3)
        }

        do {
            let content = try await SCShareableContent.excludingDesktopWindows(false, onScreenWindowsOnly: false)
            guard let display = content.displays.first else {
                fputs("ERROR: No display found\n", stderr)
                exit(1)
            }

            let filter = SCContentFilter(display: display, excludingWindows: [])
            let config = SCStreamConfiguration()
            config.capturesAudio = true
            config.excludesCurrentProcessAudio = true
            config.sampleRate = 48000
            config.channelCount = 2
            config.width = 2
            config.height = 2
            config.minimumFrameInterval = CMTime(value: 1, timescale: 1)

            let scStream = SCStream(filter: filter, configuration: config, delegate: nil)
            try scStream.addStreamOutput(captureOutput, type: .screen, sampleHandlerQueue: DispatchQueue(label: "screen.dummy"))
            try scStream.addStreamOutput(captureOutput, type: .audio, sampleHandlerQueue: DispatchQueue(label: "audio.capture"))
            try await scStream.startCapture()
            self.stream = scStream
            captureOutput.startKeepAlive()
            fputs("CAPTURE_STARTED\n", stderr)
            fflush(stderr)

            while true {
                try await Task.sleep(nanoseconds: 1_000_000_000)
            }
        } catch {
            fputs("ERROR: \(error.localizedDescription)\n", stderr)
            exit(2)
        }
    }
}
