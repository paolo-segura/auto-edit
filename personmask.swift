// Writes a greyscale person mask video using Apple's built-in Vision framework. Usage: personmask in.mp4 mask.mp4 [FRAMES]
// FRAMES, such as 60-120,300-390, limits the work to those frames (end excluded); the rest come out black.
import AVFoundation
import CoreImage
import Vision

let args = CommandLine.arguments
let wanted: [Range<Int>]? = args.count > 3 ? args[3].split(separator: ",").map { part in
    let ends = part.split(separator: "-").map { Int($0)! }
    return ends[0]..<ends[1]
} : nil
let asset = AVURLAsset(url: URL(fileURLWithPath: args[1]))
let track = asset.tracks(withMediaType: .video)[0]
let size = track.naturalSize
let reader = try AVAssetReader(asset: asset)
let output = AVAssetReaderTrackOutput(track: track, outputSettings: [kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA])
reader.add(output)
let out = URL(fileURLWithPath: args[2])
try? FileManager.default.removeItem(at: out)
let writer = try AVAssetWriter(outputURL: out, fileType: .mp4)
let input = AVAssetWriterInput(mediaType: .video, outputSettings: [
    AVVideoCodecKey: AVVideoCodecType.h264, AVVideoWidthKey: size.width, AVVideoHeightKey: size.height,
    AVVideoCompressionPropertiesKey: [AVVideoAverageBitRateKey: 20_000_000]])
let adaptor = AVAssetWriterInputPixelBufferAdaptor(assetWriterInput: input, sourcePixelBufferAttributes: nil)
writer.add(input)
reader.startReading()
writer.startWriting()
writer.startSession(atSourceTime: .zero)

let request = VNGeneratePersonSegmentationRequest()
request.qualityLevel = .accurate
request.outputPixelFormat = kCVPixelFormatType_OneComponent8
let context = CIContext()
let sequence = VNSequenceRequestHandler()
var count = 0
while let sample = output.copyNextSampleBuffer() {
    let frame = CMSampleBufferGetImageBuffer(sample)!
    var image = CIImage(color: .black).cropped(to: CGRect(origin: .zero, size: size))
    let needed = wanted?.contains { $0.contains(count) } ?? true
    if needed {
        try sequence.perform([request], on: frame)
    }
    if needed, let mask = request.results?.first?.pixelBuffer {
        let raw = CIImage(cvPixelBuffer: mask)
        image = raw.transformed(by: CGAffineTransform(scaleX: size.width / raw.extent.width, y: size.height / raw.extent.height))
    }
    var buffer: CVPixelBuffer?
    CVPixelBufferCreate(nil, Int(size.width), Int(size.height), kCVPixelFormatType_32BGRA, nil, &buffer)
    context.render(image, to: buffer!)
    while !input.isReadyForMoreMediaData { usleep(1000) }
    adaptor.append(buffer!, withPresentationTime: CMSampleBufferGetPresentationTimeStamp(sample))
    count += 1
}
input.markAsFinished()
let done = DispatchSemaphore(value: 0)
writer.finishWriting { done.signal() }
done.wait()
print("\(count) frames")
