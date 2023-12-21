import os
import torch
import datetime
import numpy as np
from PIL import Image
from pipeline_stable_video_diffusion_controlnet import StableVideoDiffusionPipelineControlNet
from controlnet_sdv import ControlNetSDVModel
from unet_spatio_temporal_condition_controlnet import UNetSpatioTemporalConditionControlNetModel
import cv2
import re 

def save_gifs_side_by_side(batch_output, validation_images, validation_control_images, output_folder):
    # Helper function to convert tensors to PIL images and save as GIF
    def create_gif(image_list, gif_path, duration=100):
        pil_images = [validate_and_convert_image(img) for img in image_list]
        pil_images = [img for img in pil_images if img is not None]
        if pil_images:
            pil_images[0].save(gif_path, save_all=True, append_images=pil_images[1:], loop=0, duration=duration)

    # Creating GIFs for each image list
    timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    gif_paths = []
    for idx, image_list in enumerate([validation_images, validation_control_images, batch_output]):
        gif_path = os.path.join(output_folder, f"temp_{idx}_{timestamp}.gif")
        create_gif(image_list, gif_path)
        gif_paths.append(gif_path)

    # Function to combine GIFs side by side
    def combine_gifs_side_by_side(gif_paths, output_path):
        gifs = [Image.open(gif) for gif in gif_paths]

        # Assuming all gifs have the same frame count and duration
        frames = []
        for frame_idx in range(len(gifs[0].n_frames)):
            combined_frame = None
            for gif in gifs:
                gif.seek(frame_idx)
                if combined_frame is None:
                    combined_frame = gif.copy()
                else:
                    combined_frame = get_concat_h(combined_frame, gif.copy())
            frames.append(combined_frame)

        frames[0].save(output_path, save_all=True, append_images=frames[1:], loop=0, duration=gifs[0].info['duration'])

    # Helper function to concatenate images horizontally
    def get_concat_h(im1, im2):
        dst = Image.new('RGB', (im1.width + im2.width, max(im1.height, im2.height)))
        dst.paste(im1, (0, 0))
        dst.paste(im2, (im1.width, 0))
        return dst

    # Combine the GIFs into a single file
    combined_gif_path = os.path.join(output_folder, f"combined_frames_{timestamp}.gif")
    combine_gifs_side_by_side(gif_paths, combined_gif_path)

    # Clean up temporary GIFs
    for gif_path in gif_paths:
        os.remove(gif_path)

    return combined_gif_path

# Define functions
def validate_and_convert_image(image, target_size=(256, 256)):
    if image is None:
        print("Encountered a None image")
        return None

    if isinstance(image, torch.Tensor):
        # Convert PyTorch tensor to PIL Image
        if image.ndim == 3 and image.shape[0] in [1, 3]:  # Check for CxHxW format
            if image.shape[0] == 1:  # Convert single-channel grayscale to RGB
                image = image.repeat(3, 1, 1)
            image = image.mul(255).clamp(0, 255).byte().permute(1, 2, 0).cpu().numpy()
            image = Image.fromarray(image)
        else:
            print(f"Invalid image tensor shape: {image.shape}")
            return None
    elif isinstance(image, Image.Image):
        # Resize PIL Image
        image = image.resize(target_size)
    else:
        print("Image is not a PIL Image or a PyTorch tensor")
        return None
    
    return image

def create_image_grid(images, rows, cols, target_size=(256, 256)):
    valid_images = [validate_and_convert_image(img, target_size) for img in images]
    valid_images = [img for img in valid_images if img is not None]

    if not valid_images:
        print("No valid images to create a grid")
        return None

    w, h = target_size
    grid = Image.new('RGB', size=(cols * w, rows * h))

    for i, image in enumerate(valid_images):
        grid.paste(image, box=((i % cols) * w, (i // cols) * h))

    return grid

def tensor_to_pil(tensor):
    """ Convert a PyTorch tensor to a PIL Image. """
    # Convert tensor to numpy array
    if len(tensor.shape) == 4:  # batch of images
        images = [Image.fromarray(img.numpy().transpose(1, 2, 0)) for img in tensor]
    else:  # single image
        images = Image.fromarray(tensor.numpy().transpose(1, 2, 0))
    return images

def save_combined_frames(batch_output, validation_images, validation_control_images, output_folder):
    # Flatten batch_output to a list of PIL Images
    flattened_batch_output = [img for sublist in batch_output for img in sublist]

    # Convert tensors in lists to PIL Images
    validation_images = [tensor_to_pil(img) if torch.is_tensor(img) else img for img in validation_images]
    validation_control_images = [tensor_to_pil(img) if torch.is_tensor(img) else img for img in validation_control_images]
    flattened_batch_output = [tensor_to_pil(img) if torch.is_tensor(img) else img for img in flattened_batch_output]

    # Flatten lists if they contain sublists (for tensors converted to multiple images)
    validation_images = [img for sublist in validation_images for img in (sublist if isinstance(sublist, list) else [sublist])]
    validation_control_images = [img for sublist in validation_control_images for img in (sublist if isinstance(sublist, list) else [sublist])]
    flattened_batch_output = [img for sublist in flattened_batch_output for img in (sublist if isinstance(sublist, list) else [sublist])]

    # Combine frames into a list
    combined_frames = validation_images + validation_control_images + flattened_batch_output

    # Calculate rows and columns for the grid
    num_images = len(combined_frames)
    cols = 3
    rows = (num_images + cols - 1) // cols

    # Create and save the grid image
    grid = create_image_grid(combined_frames, rows, cols, target_size=(256, 256))
    if grid is not None:
        timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        filename = f"combined_frames_{timestamp}.png"
        output_path = os.path.join(output_folder, filename)
        grid.save(output_path)
    else:
        print("Failed to create image grid")

def load_images_from_folder(folder):
    images = []
    valid_extensions = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".tiff"}  # Add or remove extensions as needed

    # Function to extract frame number from the filename
    def frame_number(filename):
        parts = filename.split('_')
        if len(parts) > 1 and parts[0] == 'frame':
            try:
                return int(parts[1].split('.')[0])  # Extracting the number part
            except ValueError:
                return float('inf')  # In case of non-integer part, place this file at the end
        return float('inf')  # Non-frame files are placed at the end

    # Sorting files based on frame number
    sorted_files = sorted(os.listdir(folder), key=frame_number)

    # Load images in sorted order
    for filename in sorted_files:
        ext = os.path.splitext(filename)[1].lower()
        if ext in valid_extensions:
            img = Image.open(os.path.join(folder, filename)).convert('RGB')
            images.append(img)

    return images

def load_images_from_folder_to_pil(folder, target_size=(512, 512)):
    images = []
    valid_extensions = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".tiff"}  # Add or remove extensions as needed

    def frame_number(filename):
        match = re.search(r'\d+', filename)  # Search for the first sequence of digits in the filename
        if match:
            return int(match.group())  # Convert the found digits to an integer
        return float('inf')  # Return 'inf' if no number is found

    # Sorting files based on frame number
    sorted_files = sorted(os.listdir(folder), key=frame_number)

    # Load, resize, and convert images
    for filename in sorted_files:
        ext = os.path.splitext(filename)[1].lower()
        if ext in valid_extensions:
            img_path = os.path.join(folder, filename)
            img = cv2.imread(img_path, cv2.IMREAD_UNCHANGED)  # Read image with original channels
            if img is not None:
                # Resize image
                img = cv2.resize(img, target_size, interpolation=cv2.INTER_AREA)

                # Convert to uint8 if necessary
                if img.dtype == np.uint16:
                    img = (img / 256).astype(np.uint8)

                # Ensure all images are in RGB format
                if len(img.shape) == 2:  # Grayscale image
                    img = cv2.cvtColor(img, cv2.COLOR_GRAY2RGB)
                elif len(img.shape) == 3 and img.shape[2] == 3:  # Color image in BGR format
                    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

                # Convert the numpy array to a PIL image
                pil_img = Image.fromarray(img)
                images.append(pil_img)

    return images

# Usage example

# Main script
if __name__ == "__main__":
    args = {
        "pretrained_model_name_or_path": "stabilityai/stable-video-diffusion-img2vid",
        "validation_image_folder": "./run_tests/3/rgb",
        "validation_control_folder": "./run_tests/3/depth",
        "validation_image": "./run_tests/3/scene.png",
        "output_dir": "./output",
        "height": 512,
        "width": 512,
        # Additional arguments can be added here
    }

    # Load validation images and control images
    validation_images = load_images_from_folder_to_pil(args["validation_image_folder"])
    validation_control_images = load_images_from_folder_to_pil(args["validation_control_folder"])
    validation_image = Image.open(args["validation_image"]).convert('RGB')


    # Load and set up the pipeline
    controlnet = controlnet = ControlNetSDVModel.from_pretrained("./controlnet")
    unet = UNetSpatioTemporalConditionControlNetModel.from_pretrained(args["pretrained_model_name_or_path"],subfolder="unet")
    pipeline = StableVideoDiffusionPipelineControlNet.from_pretrained(args["pretrained_model_name_or_path"],controlnet=controlnet,unet=unet)
    pipeline.enable_model_cpu_offload()
    # Additional pipeline configurations can be added here
    #pipeline.enable_xformers_memory_efficient_attention()
    # Create output directory if it doesn't exist
    val_save_dir = os.path.join(args["output_dir"], "validation_images")
    os.makedirs(val_save_dir, exist_ok=True)

    # Inference and saving loop

    video_frames = pipeline(validation_image, validation_control_images[:14], decode_chunk_size=8,num_frames=14).frames

    save_gifs_side_by_side(video_frames,validation_images, validation_control_images,val_save_dir).frames
    #save_combined_frames(video_frames, validation_images, validation_control_images,val_save_dir)