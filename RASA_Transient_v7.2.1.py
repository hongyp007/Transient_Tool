"""
Transient Detection Tool
Version: 7.2
Author: YoungPyo Hong
Date: 2024-11-05

A GUI application for viewing and classifying astronomical transient candidates.
Supports FITS and PNG image formats with configurable display settings and 
classification categories.
"""
# Standard library imports
import glob
import logging
import os
import re
import threading
import configparser
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

# Third-party imports
import numpy as np
import pandas as pd
from astropy.io import fits
from astropy.visualization import ZScaleInterval
from matplotlib import colors
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
from matplotlib.widgets import Slider
import matplotlib.pyplot as plt
from tkinter import (Button, Checkbutton, Entry, Frame, IntVar, Label, 
                    Tk, ttk, Text, messagebox)
from tkinter.ttk import Progressbar, Style


def handle_exceptions(func):
    """Decorator to handle exceptions and show error messages in user-facing methods."""
    def wrapper(self, *args, **kwargs):
        try:
            return func(self, *args, **kwargs)
        except Exception as e:
            logging.exception(f"Error in {func.__name__}: {e}")
            messagebox.showerror("Error", f"An error occurred: {e}")
    return wrapper

@dataclass
class Config:
    """
    Configuration settings for the TransientTool application.
    
    Attributes:
        data_directory (str): Base directory containing image files
        file_pattern (str): Pattern for matching image files
        output_csv_file (str): Path to save classification results
        zoom_min (float): Minimum zoom level
        zoom_max (float): Maximum zoom level
        zoom_step (float): Zoom increment/decrement step
        initial_zoom (float): Default zoom level on startup
        default_sci_ref_visible (bool): Show reference image by default
        scale (str): Image scaling type ('zscale', 'linear', 'log')
        vmin_subtracted (str): Minimum value setting for subtracted images
        vmax_subtracted (str): Maximum value setting for subtracted images
        vmin_science (str): Minimum value setting for science images
        vmax_science (str): Maximum value setting for science images
        vmin_reference (str): Minimum value setting for reference images
        vmax_reference (str): Maximum value setting for reference images
        log_file (str): Path to log file
        log_level (str): Logging level
        shortcuts (Dict[str, str]): Keyboard shortcuts mapping
        file_type (str): Image file type ('fits' or 'png')
        tile_ids (List[str]): List of tile IDs to process
        cache_size (int): Maximum number of images to cache
        classification_labels (List[str]): Available classification categories
        view_mode (bool): View-only mode flag
        specific_view_mode (Optional[str]): Specific classification view filter
    """
    data_directory: str
    file_pattern: str
    output_csv_file: str
    zoom_min: float
    zoom_max: float
    zoom_step: float
    initial_zoom: float
    default_sci_ref_visible: bool
    scale: str
    vmin_subtracted: str
    vmax_subtracted: str
    vmin_science: str
    vmax_science: str
    vmin_reference: str
    vmax_reference: str
    log_file: str
    log_level: str
    shortcuts: Dict[str, str]
    file_type: str
    tile_ids: List[str]
    cache_size: int
    classification_labels: List[str]
    view_mode: bool = False
    specific_view_mode: Optional[str] = None

    @staticmethod
    def load_config(config_path: str = 'RASA_config.ini') -> 'Config':
        """
        Load and validate configuration settings from INI file.
        
        Args:
            config_path: Path to configuration file
            
        Returns:
            Config object with loaded settings
            
        Raises:
            ValueError: If required settings are missing or invalid
        """
        config = configparser.ConfigParser()
        config.read(config_path)

        def get_config_option(section: str, option: str, type_func: Any, default: Any) -> Any:
            """
            Get config option value, ignoring comments after #.
            
            Args:
                section: Config section name
                option: Option name within section
                type_func: Type conversion function
                default: Default value if option not found
                
            Returns:
                Converted option value or default
            """
            try:
                # Get raw value and strip comments after #
                value = config.get(section, option)
                if '#' in value:
                    value = value.split('#')[0].strip()
                    
                # Handle special case for None values
                if value.lower() == 'none':
                    return None
                    
                # Handle boolean values specially
                if type_func == bool:
                    return value.lower() in ['true', '1', 'yes']
                    
                # Convert value to specified type
                return type_func(value)
                
            except (configparser.NoSectionError, configparser.NoOptionError):
                return default
            
            except ValueError as e:
                logging.warning(f"Error parsing {option} from config: {e}")
                return default

        # Load shortcuts
        shortcuts = {}
        if config.has_section('Shortcuts'):
            for key in config.options('Shortcuts'):
                shortcuts[key] = config.get('Shortcuts', key).split('#')[0].strip()

        # Load mode settings
        view_mode = get_config_option('Mode', 'view_mode', bool, False)
        specific_view_mode = get_config_option('Mode', 'specific_view_mode', str, None)

        # Load tile IDs
        tile_ids = [tid.strip() for tid in 
                   config.get('TileSettings', 'tile_ids', fallback='').split(',')]
        if not tile_ids:
            raise ValueError("No tile IDs specified in config")

        # Load classification labels
        classification_labels = [label.strip() for label in 
                              config.get('Settings', 'classification_labels', fallback='').split(',')]

        # Create config instance with all labels
        config = Config(
            data_directory=get_config_option('Paths', 'data_directory', str, ''),
            file_pattern=get_config_option('Paths', 'file_pattern', str, ''),
            output_csv_file=get_config_option('Paths', 'output_csv_file', str, ''),
            zoom_min=get_config_option('Settings', 'zoom_min', float, 1.0),
            zoom_max=get_config_option('Settings', 'zoom_max', float, 10.0),
            zoom_step=get_config_option('Settings', 'zoom_step', float, 0.1),
            initial_zoom=get_config_option('Settings', 'initial_zoom', float, 1.0),
            default_sci_ref_visible=get_config_option('Settings', 'default_sci_ref_visible',
                                                     lambda x: x.lower() in ['true', '1', 'yes'], True),
            scale=get_config_option('Settings', 'scale', str, 'zscale').lower(),
            vmin_subtracted=get_config_option('Settings', 'vmin_subtracted', str, 'median').lower(),
            vmax_subtracted=get_config_option('Settings', 'vmax_subtracted', str, 'max').lower(),
            vmin_science=get_config_option('Settings', 'vmin_science', str, 'median').lower(),
            vmax_science=get_config_option('Settings', 'vmax_science', str, 'max').lower(),
            vmin_reference=get_config_option('Settings', 'vmin_reference', str, 'median').lower(),
            vmax_reference=get_config_option('Settings', 'vmax_reference', str, 'max').lower(),
            log_file=get_config_option('Logging', 'log_file', str, 'transient_tool.log'),
            log_level=get_config_option('Logging', 'log_level', str, 'INFO').upper(),
            shortcuts=shortcuts,
            file_type=get_config_option('Settings', 'file_type', str, 'fits').lower(),
            view_mode=view_mode,
            specific_view_mode=specific_view_mode,
            tile_ids=tile_ids,
            cache_size=config.getint('TileSettings', 'cache_size', fallback=100),
            classification_labels=classification_labels
        )

        # Validation of required fields
        required_options = ['data_directory', 'file_pattern', 'output_csv_file']
        for option in required_options:
            if not getattr(config, option):
                raise ValueError(f"Missing required configuration option: {option} in section 'Paths'.")

        # Validate scale option
        if config.scale not in ['zscale', 'linear', 'log']:
            logging.warning(f"Invalid scale '{config.scale}' in configuration. Using 'linear' as default.")
            config.scale = 'linear'

        # Validate file_type option
        if config.file_type not in ['fits', 'png']:
            raise ValueError("Invalid file_type option in configuration. Choose 'fits' or 'png'.")

        return config

class DataManager:
    """
    Handles data loading, processing and persistence for astronomical images.
    
    Manages the loading, processing, and saving of image data and classifications.
    Maintains a DataFrame of all images and their metadata.
    
    Attributes:
        config (Config): Configuration settings
        file_lock (threading.Lock): Thread lock for file operations
        region_df (pd.DataFrame): DataFrame containing image metadata and classifications
        image_processor (ImageProcessor): Handler for image processing operations
        data_validator (DataValidator): Validator for data integrity
        index (int): Current image index
    """

    def __init__(self, config: Config):
        """
        Initialize DataManager with configuration settings.
        
        Args:
            config: Configuration object containing all settings
            
        Raises:
            FileNotFoundError: If no valid files found for specified tile IDs
            ValueError: If required configuration options are missing
        """
        self.config = config
        self.file_lock = threading.Lock()
        self.region_df = pd.DataFrame()
        self.image_processor = ImageProcessor(config)
        self.data_validator = DataValidator(config)  # Initialize DataValidator
        
        # Load files and initialize DataFrame
        self.load_files()
        self.init_dataframe()
        
        # Ensure Memo column is string type and replace NaN with empty string
        self.region_df['Memo'] = self.region_df['Memo'].astype(str).replace('nan', '')
        
        # Get starting index
        self.index = self.get_starting_index()
        logging.info("DataManager initialized.")

    def load_files(self):
        """Load and sort image files based on unique identifiers per tile ID."""
        try:
            file_data = []
            base_dir = self.config.data_directory
            
            # Clean tile_ids - remove any whitespace
            tile_ids = [tid.strip() for tid in self.config.tile_ids]
            
            for tile_id in tile_ids:
                # Replace T* with actual tile ID in file pattern
                pattern = self.config.file_pattern.replace('T*', tile_id)
                full_pattern = os.path.join(base_dir, f"{pattern}*.com.*.sub.{self.config.file_type}")
                
                # Find all matching subtracted image files
                sub_files = glob.glob(full_pattern)
                logging.info(f"Found {len(sub_files)} files for tile {tile_id}")
                
                # Extract unique identifiers from filenames
                for filename in sub_files:
                    unique_number = self.get_unique_number(filename)
                    if unique_number is not None:
                        file_data_dict = {
                            'tile_id': tile_id,
                            'unique_number': unique_number,
                        }
                        file_data.append(file_data_dict)

            # Create DataFrame with only tile_id and unique_number
            self.region_df = pd.DataFrame(file_data)
            if not self.region_df.empty:
                self.region_df.sort_values(['tile_id', 'unique_number'], inplace=True)
                self.region_df.reset_index(drop=True, inplace=True)
                logging.info(f"Loaded {len(self.region_df)} total files")
            else:
                logging.error("No valid files found for specified tile IDs")
                raise FileNotFoundError("No valid files found for specified tile IDs")

        except Exception as e:
            logging.exception(f"Error loading files: {e}")
            raise

    @staticmethod
    def get_unique_number(filename: str) -> Optional[int]:
        """
        Extract unique identifier from filename.
        
        Args:
            filename: Full path to image file
            
        Returns:
            Unique number from filename or None if not found
            
        Example:
            >>> get_unique_number("path/to/com.123.sub.fits")
            123
        """
        basename = os.path.basename(filename)
        match = re.search(r'com\.(\d+)\.', basename)
        if match:
            return int(match.group(1))
        return None

    def get_tile_id(self, filename: str) -> Optional[str]:
        """
        Extract tile ID from filename.
        Expected format: 'T<number>' in the filename
        Returns the full ID including 'T' prefix
        """
        match = re.search(r'(T\d+)', filename)
        if match:
            return match.group(1)
        return None

    def init_dataframe(self):
        """Initialize or merge with existing classification data from CSV."""
        try:
            existing_data = None
            if os.path.exists(self.config.output_csv_file):
                # Load existing CSV
                existing_data = pd.read_csv(self.config.output_csv_file)
                existing_data = existing_data[existing_data['tile_id'] != 'Total']
                
                # Ensure data types are consistent
                existing_data['unique_number'] = pd.to_numeric(existing_data['unique_number'], errors='coerce')
                existing_data['tile_id'] = existing_data['tile_id'].astype(str)
                existing_data['Memo'] = existing_data['Memo'].astype(str)  # Convert Memo to string type

            # If we have existing data, merge it with the new file list
            if existing_data is not None and not existing_data.empty:
                # Merge on tile_id and unique_number
                self.region_df = pd.merge(
                    self.region_df,
                    existing_data,
                    on=['tile_id', 'unique_number'],
                    how='left'
                )
            else:
                # Add default columns if no existing data
                self.region_df['Memo'] = ''
                self.region_df['Scale'] = self.config.scale
                for label in self.config.classification_labels:
                    self.region_df[label] = 0

            # Ensure all required columns exist with proper defaults
            for col in self.config.classification_labels:
                if col not in self.region_df.columns:
                    self.region_df[col] = 0
                self.region_df[col] = self.region_df[col].fillna(0).astype(int)

            # Ensure Memo column is string type
            if 'Memo' not in self.region_df.columns:
                self.region_df['Memo'] = ''
            self.region_df['Memo'] = self.region_df['Memo'].fillna('').astype(str)

            if 'Scale' not in self.region_df.columns:
                self.region_df['Scale'] = self.config.scale

            # Final sorting and cleanup
            self.region_df = self.region_df.sort_values(['tile_id', 'unique_number'])
            self.region_df = self.region_df.reset_index(drop=True)
            
            logging.info(f"DataFrame initialized with {len(self.region_df)} rows")
            
            # Save the initialized DataFrame
            self.save_dataframe()

        except Exception as e:
            logging.error(f"Error initializing DataFrame: {e}")
            raise

    def get_starting_index(self) -> int:
        """
        Determine starting index based on first unprocessed image.
        
        Returns:
            int: Index of first unprocessed image, or 0 if all are processed
        """
        try:
            if self.region_df.empty:
                return 0
                
            # Find first unclassified image
            unclassified = self.region_df[
                ~self.region_df[self.config.classification_labels].any(axis=1)
            ]
            
            if unclassified.empty:
                logging.info("All images are classified")
                return 0
                
            # Get the first unclassified entry's index
            first_unclassified_index = unclassified.index[0]
            
            logging.info(f"Starting from first unclassified image at index {first_unclassified_index}")
            return first_unclassified_index
            
        except Exception as e:
            logging.error(f"Error getting starting index: {e}")
            return 0

    def save_dataframe(self, callback=None):
        """Save the DataFrame to CSV with totals."""
        try:
            # Validate DataFrame before saving
            is_valid, errors = self.data_validator.validate_dataframe(self.region_df)
            if not is_valid:
                error_msg = "\n".join(errors)
                logging.error(f"DataFrame validation failed:\n{error_msg}")
                raise ValueError(f"DataFrame validation failed:\n{error_msg}")

            # Create a copy to avoid modifying the original
            df_to_save = self.region_df.copy()
            
            # Clean up memo field - replace NaN with empty string
            df_to_save['Memo'] = df_to_save['Memo'].fillna('').astype(str)
            
            # Calculate totals for classifications
            totals = {}
            for col in self.config.classification_labels:
                totals[col] = int(df_to_save[col].sum())
            
            # Count unique tile IDs and total images    
            tile_count = len(df_to_save['tile_id'].unique())
            total_images = len(df_to_save)
            
            # Count processed images (any classification column is 1)   
            total_processed_images = len(df_to_save[
                df_to_save[self.config.classification_labels].any(axis=1)
            ])

            # Create total row
            total_dict = {
                'tile_id': tile_count,
                'unique_number': total_images,  # Number of unique tile IDs
                'Memo': total_processed_images,  # Total number of images
                'Scale': 'Total',  # Number of processed images
            }
            total_dict.update(totals)

            # Add total row to the DataFrame
            df_with_total = pd.concat([df_to_save, pd.DataFrame([total_dict])], ignore_index=True)

            # Save to CSV with proper locking
            with self.file_lock:
                df_with_total.to_csv(self.config.output_csv_file, index=False, na_rep='')
                logging.info(f"DataFrame saved successfully to {self.config.output_csv_file}")
                logging.debug(f"Total unique tile IDs: {tile_count}")
                logging.debug(f"Total images: {total_images}")
                logging.debug(f"Processed images: {total_processed_images}")
                logging.debug(f"Classification totals: {totals}")

        except Exception as e:
            logging.error(f"Error saving DataFrame: {e}")
            raise

    def load_image_data(self, index: int) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        Load all image data for the current index using ImageProcessor.
        Delegates actual loading to ImageProcessor.
        """
        try:
            index = int(index)
            
            if index < 0 or index >= len(self.region_df):
                raise ValueError(f"Index {index} out of bounds for DataFrame with {len(self.region_df)} rows")
                
            current_row = self.region_df.iloc[index]
            tile_id = current_row['tile_id']
            unique_number = current_row['unique_number']
            
            # Use ImageProcessor to load and process images
            return self.image_processor.load_and_process_images(tile_id, unique_number)
                
        except Exception as e:
            logging.error(f"Error in load_image_data: {e}")
            raise

class DataValidator:
    """Class to handle data validation."""
    
    def __init__(self, config: Config):
        self.config = config
        
    def validate_dataframe(self, df: pd.DataFrame) -> Tuple[bool, List[str]]:
        """
        Validate DataFrame structure and content.
        Single source of truth for DataFrame validation.
        """
        errors = []
        
        try:
            # Validate required columns
            errors.extend(self._validate_columns(df))
            
            # Validate data types
            errors.extend(self._validate_data_types(df))
            
            # Validate classification values
            errors.extend(self._validate_classifications(df))
            
            return len(errors) == 0, errors
            
        except Exception as e:
            errors.append(f"Validation error: {str(e)}")
            return False, errors
            
    def _validate_columns(self, df: pd.DataFrame) -> List[str]:
        """Validate required columns exist."""
        errors = []
        required_cols = ['tile_id', 'unique_number', 'Memo', 'Scale'] + self.config.classification_labels
        missing_cols = [col for col in required_cols if col not in df.columns]
        if missing_cols:
            errors.append(f"Missing required columns: {missing_cols}")
        return errors
        
    def _validate_data_types(self, df: pd.DataFrame) -> List[str]:
        """Validate data types of key columns."""
        errors = []
        if 'unique_number' in df.columns:
            if not pd.to_numeric(df['unique_number'], errors='coerce').notna().all():
                errors.append("Invalid unique_number values found")
        return errors
        
    def _validate_classifications(self, df: pd.DataFrame) -> List[str]:
        """Validate classification column values."""
        errors = []
        for col in self.config.classification_labels:
            if col in df.columns:
                invalid = ~df[col].isin([0, 1, np.nan])
                if invalid.any():
                    invalid_rows = df.loc[invalid, 'unique_number'].tolist()
                    errors.append(f"Invalid {col} values in rows: {invalid_rows}")
        return errors

class ImageProcessor:
    """
    Handles image processing operations and caching.
    
    Provides methods for loading, processing, and caching astronomical images.
    Handles different file types (FITS/PNG) and applies appropriate scaling.
    
    Attributes:
        config (Config): Configuration settings
        image_cache (Dict): Cache of loaded images
        cache_size (int): Maximum number of images to cache
    """
    def __init__(self, config: Config):
        self.config = config
        self.image_cache = {}
        self.cache_size = config.cache_size
        
    def load_and_process_images(self, tile_id: str, unique_number: int) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        Load and process all image types for a given identifier.
        Single source of truth for image loading.
        """
        cache_key = f"{tile_id}_{unique_number}"
        
        # Check cache first
        if cache_key in self.image_cache:
            return self.image_cache[cache_key]
            
        try:
            # Get image paths
            paths = self._get_image_paths(tile_id, unique_number)
            
            # Load images
            sub_data = self._load_single_image(paths['sub'][0]) if paths['sub'] else None
            new_data = self._load_single_image(paths['new'][0]) if paths['new'] else None
            ref_data = self._load_single_image(paths['ref'][0]) if paths['ref'] else None
            
            # Cache results
            self._update_cache(cache_key, (sub_data, new_data, ref_data))
            
            return sub_data, new_data, ref_data
            
        except Exception as e:
            logging.error(f"Error loading/processing images for {tile_id}-{unique_number}: {e}")
            raise
            
    def _get_image_paths(self, tile_id: str, unique_number: int) -> dict:
        """Get paths for all image types."""
        base_pattern = self.config.file_pattern.replace('T*', tile_id)
        base_path = os.path.join(self.config.data_directory, f"{base_pattern}*.com.{unique_number}")
        
        return {
            'sub': glob.glob(f"{base_path}.sub.{self.config.file_type}"),
            'new': glob.glob(f"{base_path}.new.{self.config.file_type}"),
            'ref': glob.glob(f"{base_path}.ref.{self.config.file_type}")
        }
        
    def _load_single_image(self, filepath: str) -> np.ndarray:
        """Load a single image file."""
        try:
            if not os.path.exists(filepath):
                raise FileNotFoundError(f"Image file not found: {filepath}")

            elif self.config.file_type == 'fits':
                with fits.open(filepath) as hdul:
                    data = hdul[0].data
                    if data is None:
                        raise ValueError(f"No data found in FITS file: {filepath}")
                    return data
            elif self.config.file_type == 'png':
                data = plt.imread(filepath)
                if data is None:
                    raise ValueError(f"No data found in PNG file: {filepath}")
                return data
            
            else:
                raise ValueError(f"Unsupported file type: {self.config.file_type}")
                
        except Exception as e:
            logging.error(f"Error loading image {filepath}: {e}")
            raise
            
    def _update_cache(self, key: str, value: Tuple[np.ndarray, np.ndarray, np.ndarray]):
        """Update image cache, removing oldest entry if necessary."""
        if len(self.image_cache) >= self.cache_size:
            # Remove oldest entry
            oldest_key = next(iter(self.image_cache))
            del self.image_cache[oldest_key]
        self.image_cache[key] = value
        
    def prepare_normalization(self, image: np.ndarray, vmin: Optional[float], vmax: Optional[float]) -> Any:
        """
        Create image normalization based on configured scale type.
        
        Args:
            image: Image data
            vmin: Minimum value setting ('min', 'median', etc.)
            vmax: Maximum value setting ('max', 'median', etc.)
            
        Returns:
            Matplotlib normalization object
        """
        try:
            # Only convert to float if needed
            if image.dtype != np.float32 and image.dtype != np.float64:
                image = image.astype(np.float32)
            
            # Get min/max values using validate_value
            v_min = self.validate_value(vmin, image) if isinstance(vmin, str) else vmin
            v_max = self.validate_value(vmax, image) if isinstance(vmax, str) else vmax
            
            # Get actual min/max values based on settings
            if self.config.scale == 'zscale':
                interval = ZScaleInterval()
                v_min, v_max = interval.get_limits(image)
                return colors.Normalize(vmin=v_min, vmax=v_max)
                
            elif self.config.scale == 'log':
                return colors.LogNorm(vmin=v_min, vmax=v_max)
                
            else:  # 'linear'
                return colors.Normalize(vmin=v_min, vmax=v_max)
                
        except Exception as e:
            logging.error(f"Error preparing normalization: {e}")
            return colors.Normalize()
            
    def validate_value(self, value: str, image: np.ndarray) -> float:
        """
        Validate and calculate value based on string descriptor.
        
        Args:
            value: String descriptor ('max', 'min', etc.) or float value
            image: Image data to calculate statistics from
            
        Returns:
            float: Calculated value
        """
        try:
            if value == 'max':
                return np.max(image)
            elif value == 'min':
                return np.min(image)
            elif value == 'median':
                return np.median(image)
            elif value == 'mean':
                return np.mean(image)
            elif value == 'std':
                return np.std(image)
            else:
                return float(value)
        except Exception as e:
            logging.error(f"Error validating value: {e}")
            raise ValueError(f"Invalid value: {value}")

class TransientTool:
    """
    GUI application for classifying transient astronomical objects.
    
    Provides a graphical interface for viewing and classifying astronomical images,
    with support for image navigation, zooming, and classification management.
    
    Attributes:
        master (Tk): Root Tkinter window
        config (Config): Configuration settings
        data_manager (DataManager): Data management handler
        image_processor (ImageProcessor): Image processing handler
        index (int): Current image index
        zoom_level (float): Current zoom level
        sci_ref_visible (bool): Science/Reference image visibility flag
    """
    def __init__(self, master: Tk, config: Config):
        """Initialize the TransientTool."""
        self.master = master
        self.config = config
        self.master.title("Searching Transient Tool")

        # Initialize logging
        self.setup_logging()

        # Initialize helpers
        self.data_validator = DataValidator(config)

        # Data Manager initialization
        try:
            self.data_manager = DataManager(config)
            self.index = self.data_manager.index  # Use DataManager's index
            self.num_images = len(self.data_manager.region_df)
        except Exception as e:
            messagebox.showerror("Initialization Error", f"Failed to initialize DataManager: {e}")
            self.master.quit()
            return

        # Variables
        self.zoom_level = self.config.initial_zoom
        self.sci_ref_visible = self.config.default_sci_ref_visible
        self.current_memo = ''
        self.science_data = None
        self.reference_data = None
        self.memo_editing = False
        self.classification_buttons = {}

        # Setup UI and initialize
        self.setup_ui()
        self.bind_shortcuts()
        self.display_images()
        self.init_mode_settings()
        
        # Initialize ImageProcessor
        self.image_processor = ImageProcessor(config)
        
    def setup_logging(self):
        """
        Set up logging configuration.
        """
        logging.basicConfig(
            filename=self.config.log_file,
            level=getattr(logging, self.config.log_level, logging.INFO),
            format='%(asctime)s - %(levelname)s - %(message)s'
        )
        logging.info("Application started.")

    def setup_ui(self):
        """Initialize and layout all UI components."""
        # Configure main window grid
        self.master.rowconfigure(0, weight=1)
        self.master.columnconfigure(0, weight=1)

        # Create main frame with grid configuration
        frame = Frame(self.master)
        frame.grid(row=0, column=0, sticky='nsew')
        frame.rowconfigure(1, weight=1)
        frame.columnconfigure(0, weight=1)

        # Initialize matplotlib figure and canvas for image display
        self.fig = Figure(figsize=(12, 8))
        self.canvas = FigureCanvasTkAgg(self.fig, master=frame)
        self.canvas.get_tk_widget().configure(takefocus=1)  # Make canvas focusable
        self.canvas.get_tk_widget().grid(row=1, column=0, sticky='nsew')

        # Create subplots with adjusted spacing
        self.axes = [self.fig.add_subplot(1, 3, i + 1) for i in range(3)]
        self.fig.subplots_adjust(left=0.05, right=0.95, bottom=0.25, top=0.85, wspace=0.05)

        # Zoom Slider
        self.create_zoom_slider()

        # Memo Section
        self.create_memo_section(frame)

        # Control Buttons
        self.create_control_buttons(frame)

        # Progress Bar
        self.create_progress_bar(frame)

        # Scale, Vmin, Vmax Labels
        self.create_scale_labels(frame)

        # Directories Text
        self.create_directories_text(frame)

    def create_zoom_slider(self):
        """Create a zoom slider below the images."""
        self.zoom_ax = self.fig.add_axes([0.25, 0.1, 0.5, 0.03])
        self.zoom_slider = Slider(
            self.zoom_ax, 'Zoom', 
            self.config.zoom_min, 
            self.config.zoom_max,
            valinit=self.config.initial_zoom, 
            valstep=self.config.zoom_step
        )
        self.zoom_slider.on_changed(self.on_zoom_change)

    def on_zoom_change(self, val):
        """Handle zoom slider value changes."""
        try:
            if val != self.zoom_level:
                self.zoom_level = val
                self.view_size = [size/self.zoom_level for size in self.original_size]
                self.update_zoom()
                logging.debug(f"Zoom changed to {val}x via slider")
        except Exception as e:
            logging.error(f"Error in zoom slider change: {e}")

    def create_memo_section(self, parent_frame: Frame):
        """
        Create the memo text box with auto-enable/disable functionality.
        """
        memo_frame = Frame(parent_frame)
        memo_frame.grid(row=2, column=0, sticky='ew', padx=5, pady=5)

        # Memo Text Box
        Label(memo_frame, text="Memo:").pack(anchor='w')
        self.memo_text = Text(
            memo_frame,
            height=4,
            wrap='word',
            state='disabled',
            highlightthickness=0,             # No border initially
            bd=0,                             # No border width
            bg='#f0f0f0',                     # Light gray background to match disabled look
            fg='black'                        # Text color
        )
        self.memo_text.pack(fill='x', expand=True)

        # Bind focus events
        self.memo_text.bind('<Button-1>', self.on_memo_click)
        
        # Bind click events to the main window and all frames to handle focus loss
        self.master.bind('<Button-1>', self.check_memo_focus)
        parent_frame.bind('<Button-1>', self.check_memo_focus)
        memo_frame.bind('<Button-1>', self.check_memo_focus)

    def check_memo_focus(self, event):
        """
        Check if click was outside memo box and save/disable if necessary.
        """
        if event.widget != self.memo_text:
            self.save_and_disable_memo()

    def on_memo_click(self, event):
        """
        Enable memo editing when clicked.
        """
        if self.memo_text.cget('state') == 'disabled':
            self.memo_editing = True  # Set flag when enabling memo editing
            self.memo_text.config(
                state='normal',
                highlightthickness=2,            
                highlightbackground='blue',      
                highlightcolor='blue',           
                bg='white',                      
                fg='black'                       
            )
            logging.debug("Memo text box enabled for editing. Shortcuts disabled.")
            return "break"  

    def save_and_disable_memo(self):
        """Save memo content and disable editing."""
        if self.memo_text.cget('state') == 'normal':
            try:
                current_row = self.data_manager.region_df.iloc[self.index]
                
                # Get memo text and ensure empty string is preserved
                memo_text = self.memo_text.get('1.0', 'end').strip()
                self.current_memo = memo_text
                
                # Always store as empty string instead of NaN
                self.data_manager.region_df.at[self.index, 'Memo'] = memo_text
                
                # Save changes
                self.data_manager.save_dataframe()
                
                # Disable memo text box
                self.memo_text.config(
                    state='disabled',
                    highlightthickness=0,
                    bg='#f0f0f0',
                    fg='black'
                )
                self.memo_editing = False
                
                # Log success
                logging.info(f"Memo saved for Tile: {current_row['tile_id']}, "
                           f"Number: {current_row['unique_number']}")
                
                # Reset focus
                self.canvas.get_tk_widget().focus_set()
                
            except Exception as e:
                logging.error(f"Error saving memo: {e}")
                messagebox.showerror("Error", f"Failed to save memo: {e}")

    # Get shortcuts from config
    def get_shortcut_key(self, shortcut_name: str) -> str:
        return self.config.shortcuts.get(shortcut_name, '')
    
    def create_control_buttons(self, parent_frame: Frame):
        """
        Create classification buttons and navigation controls.
        """
        button_frame = Frame(parent_frame)
        button_frame.grid(row=3, column=0, padx=5, pady=5, sticky='ew')
        button_frame.columnconfigure((0, 1, 2, 3), weight=1)

        # Only create classification buttons if not in view mode
        if not self.config.view_mode and self.config.specific_view_mode is None:
            # Create classification buttons
            self.create_classification_buttons(button_frame)

        # Create navigation buttons (these are always visible)
        self.create_navigation_buttons(button_frame)
        

    @handle_exceptions
    def jump_to_image(self):
        """
        Jump to a specific image by index (1-based).
        """
        try:
            index = int(self.jump_entry.get())
            # Convert 1-based index to 0-based index
            zero_based_index = index - 1
            
            if 0 <= zero_based_index < self.num_images:
                self.index = zero_based_index
                self.science_data = None
                self.reference_data = None
                self.display_images()
                logging.info(f"Jumped to image {index} of {self.num_images}.")
                # Clear the entry box after successful jump
                self.jump_entry.delete(0, 'end')
            else:
                messagebox.showerror(
                    "Error", 
                    f"Please enter a number between 1 and {self.num_images}."
                )
        except ValueError:
            messagebox.showerror("Error", "Please enter a valid number.")

    def create_navigation_buttons(self, button_frame: Frame):
        """Create navigation buttons"""
        # Main navigation frame
        nav_frame = Frame(button_frame)
        nav_frame.grid(row=1, column=0, columnspan=4, pady=2)
        
        # Center the navigation buttons
        nav_buttons_frame = Frame(nav_frame)
        nav_buttons_frame.pack(expand=True)
        
        self.prev_button = Button(
            nav_buttons_frame,
            text=f"Previous ({self.config.shortcuts.get('prev_key', '')})",
            command=self.prev_image
        )
        self.prev_button.pack(side='left', padx=5)
        
        self.goto_unclassified_button = Button(
            nav_buttons_frame,
            text=f"Go to Unclassified ({self.config.shortcuts.get('goto_unclassified_key', '')})",
            command=self.goto_unclassified
        )
        self.goto_unclassified_button.pack(side='left', padx=5)
        
        self.next_button = Button(
            nav_buttons_frame,
            text=f"Next ({self.config.shortcuts.get('next_key', '')})",
            command=self.next_image
        )
        self.next_button.pack(side='left', padx=5)

        # Create a frame for all "Go to" controls
        goto_controls_frame = Frame(button_frame)
        goto_controls_frame.grid(row=2, column=0, columnspan=4, pady=2)
        
        # Center the "Go to" controls
        goto_inner_frame = Frame(goto_controls_frame)
        goto_inner_frame.pack(expand=True)
        
        # Tile ID selection controls
        tile_frame = Frame(goto_inner_frame)
        tile_frame.pack(side='left', padx=20)
        Label(tile_frame, text="Go to Tile ID:").pack(side='left', padx=2)
        sorted_tile_ids = sorted(self.config.tile_ids)
        self.tile_combobox = ttk.Combobox(tile_frame, values=sorted_tile_ids, width=10)
        self.tile_combobox.pack(side='left', padx=2)
        Button(tile_frame, text="Go", command=self.goto_tile_id).pack(side='left', padx=2)
        
        # Jump to Unique Number controls
        unique_frame = Frame(goto_inner_frame)
        unique_frame.pack(side='left', padx=20)
        Label(unique_frame, text="Go to Unique Number:").pack(side='left', padx=2)
        self.unique_entry = Entry(unique_frame, width=10)
        self.unique_entry.pack(side='left', padx=2)
        Button(unique_frame, text="Go", command=self.goto_unique_number).pack(side='left', padx=2)        
        
        # Jump to Image controls
        jump_frame = Frame(goto_inner_frame)
        jump_frame.pack(side='left', padx=20)
        Label(jump_frame, text=f"Go to Image (1-{self.num_images}):").pack(side='left', padx=2)
        self.jump_entry = Entry(jump_frame, width=10)
        self.jump_entry.pack(side='left', padx=2)
        Button(jump_frame, text="Go", command=self.jump_to_image).pack(side='left', padx=2)

        # Zoom controls
        zoom_frame = Frame(button_frame)
        zoom_frame.grid(row=5, column=0, columnspan=4, pady=2)
        
        # Center the zoom controls
        zoom_inner_frame = Frame(zoom_frame)
        zoom_inner_frame.pack(expand=True)

        self.zoom_in_button = Button(
            zoom_inner_frame,
            text=f"Zoom In ({self.config.shortcuts.get('zoom_in_key', '')})",
            command=self.zoom_in
        )
        self.zoom_in_button.pack(side='left', padx=5)

        self.reset_zoom_button = Button(
            zoom_inner_frame,
            text=f"Reset Zoom ({self.config.shortcuts.get('reset_zoom_key', '')})",
            command=self.reset_zoom
        )
        self.reset_zoom_button.pack(side='left', padx=5)

        self.zoom_out_button = Button(
            zoom_inner_frame,
            text=f"Zoom Out ({self.config.shortcuts.get('zoom_out_key', '')})",
            command=self.zoom_out
        )
        self.zoom_out_button.pack(side='left', padx=5)

        # Show Sci & Ref Image controls
        checkbox_frame = Frame(button_frame)
        checkbox_frame.grid(row=6, column=0, columnspan=4, pady=2)
        
        self.sci_ref_var = IntVar(value=int(self.sci_ref_visible))
        self.show_sci_ref_checkbox = Checkbutton(
            checkbox_frame,
            text=f"Show Sci & Ref Images ({self.config.shortcuts.get('toggle_sci_ref_key', '')})",
            variable=self.sci_ref_var,
            command=self.toggle_sci_ref_image
        )
        self.show_sci_ref_checkbox.pack(expand=True)

    def create_classification_buttons(self, button_frame: Frame):
        """Create classification buttons dynamically from config."""
        for i, label in enumerate(self.config.classification_labels):
            # Fix: Change shortcut key lookup to match config file format
            shortcut_key = self.config.shortcuts.get(f'{label.lower()}_key', '')
            button = Button(
                button_frame,
                text=f"{label} ({shortcut_key})",
                command=lambda l=label: self.save_classification(l, 1)
            )
            button.grid(row=0, column=i, padx=5, pady=2, sticky='ew')
            self.classification_buttons[label] = button
    
    def goto_unclassified(self):
        """Find and navigate to the first unclassified image."""
        try:
            # Find first unclassified image
            unclassified = self.data_manager.region_df[
                ~self.data_manager.region_df[self.config.classification_labels].any(axis=1)
            ]
            
            if not unclassified.empty:
                first_unclassified = unclassified.index[0]
                # Use jump to image functionality
                self.index = first_unclassified
                self.science_data = None
                self.reference_data = None
                self.display_images()
                logging.info(f"Moved to unclassified image: Index {first_unclassified}")
            else:
                messagebox.showinfo("Info", "No unclassified images found!")
                logging.info("No unclassified images found")
                
        except Exception as e:
            logging.error(f"Error finding unclassified image: {e}")
            raise

    def create_progress_bar(self, parent_frame: Frame):
        """
        Create a progress bar to display processing progress.
        """
        # Progress bar frame
        progress_frame = Frame(parent_frame)
        progress_frame.grid(row=4, column=0, padx=5, pady=5, sticky='ew')
        
        # Configure progress bar style
        style = Style()
        style.layout('text.Horizontal.TProgressbar',
                     [('Horizontal.Progressbar.trough',
                       {'children': [('Horizontal.Progressbar.pbar',
                                      {'side': 'left', 'sticky': 'ns'})],
                        'sticky': 'nswe'}),
                      ('Horizontal.Progressbar.label', {'sticky': ''})])
        style.configure('text.Horizontal.TProgressbar', text='0%')

        self.progress_var = IntVar()
        self.progress = Progressbar(
            progress_frame,
            variable=self.progress_var,
            maximum=100,
            style='text.Horizontal.TProgressbar'
        )
        self.progress.grid(row=0, column=0, sticky='ew', padx=5, pady=2)

        # Create status text widget
        self.status_text = Text(
            progress_frame,
            height=4,
            width=40,
            font=("Helvetica", 10),
            state='disabled'
        )
        self.status_text.grid(row=1, column=0, sticky='ew', padx=5, pady=2)

        # Configure grid weights for progress_frame
        progress_frame.columnconfigure(0, weight=1)

    def create_scale_labels(self, parent_frame: Frame):
        """
        Create labels to display scale, vmin, and vmax settings.
        """
        scale_frame = Frame(parent_frame)
        scale_frame.grid(row=5, column=0, sticky='ew', padx=5, pady=5)
        scale_frame.columnconfigure((0, 1, 2), weight=1)

        # Labels for Subtracted Image
        self.scale_sub_label = Label(scale_frame, text="Subtracted Image - Scale: ")
        self.vmin_sub_label = Label(scale_frame, text="Vmin: ")
        self.vmax_sub_label = Label(scale_frame, text="Vmax: ")

        self.scale_sub_label.grid(row=0, column=0, sticky='w')
        self.vmin_sub_label.grid(row=1, column=0, sticky='w')
        self.vmax_sub_label.grid(row=2, column=0, sticky='w')

        # Labels for Science Image
        self.scale_sci_label = Label(scale_frame, text="Science Image - Scale: ")
        self.vmin_sci_label = Label(scale_frame, text="Vmin: ")
        self.vmax_sci_label = Label(scale_frame, text="Vmax: ")

        self.scale_sci_label.grid(row=0, column=1, sticky='w', padx=(20, 0))
        self.vmin_sci_label.grid(row=1, column=1, sticky='w', padx=(20, 0))
        self.vmax_sci_label.grid(row=2, column=1, sticky='w', padx=(20, 0))

        # Labels for Reference Image
        self.scale_ref_label = Label(scale_frame, text="Reference Image - Scale: ")
        self.vmin_ref_label = Label(scale_frame, text="Vmin: ")
        self.vmax_ref_label = Label(scale_frame, text="Vmax: ")

        self.scale_ref_label.grid(row=0, column=2, sticky='w', padx=(20, 0))
        self.vmin_ref_label.grid(row=1, column=2, sticky='w', padx=(20, 0))
        self.vmax_ref_label.grid(row=2, column=2, sticky='w', padx=(20, 0))

    def create_directories_text(self, parent_frame: Frame):
        """
        Create directories text below the progress bar to prevent overlapping.
        """
        directories_frame = Frame(parent_frame)
        directories_frame.grid(row=6, column=0, sticky='ew', padx=5, pady=(0, 5))
        directories_frame.columnconfigure(0, weight=1)
        directories_text = f"Image Pattern: {self.config.file_pattern}\nCSV File: {self.config.output_csv_file}"
        Label(
            directories_frame,
            text=directories_text,
            justify='left',
            font=("Helvetica", 10)
        ).pack(anchor='w')

    def bind_shortcuts(self):
        """
        Bind keyboard shortcuts to their respective functions.
        All shortcuts are loaded from config file.
        """
        def handle_shortcut(event):
            if self.memo_editing:  # Skip if editing memo
                return
                
            key = event.keysym.lower()  # Convert to lowercase for consistent matching
            
            # Handle classification shortcuts
            for label in self.config.classification_labels:
                shortcut = self.config.shortcuts.get(f'{label.lower()}_key', '').lower()
                if key == shortcut:
                    self.save_classification(label, 1)
                    return
            
            # Handle navigation shortcuts
            if key == self.config.shortcuts.get('next_key', '').lower():
                self.next_image()
            elif key == self.config.shortcuts.get('prev_key', '').lower():
                self.prev_image()
            elif key == self.config.shortcuts.get('goto_unclassified_key', '').lower():
                self.goto_unclassified()
            elif key == self.config.shortcuts.get('zoom_in_key', '').lower():
                self.zoom_in()
            elif key == self.config.shortcuts.get('zoom_out_key', '').lower():
                self.zoom_out()
            elif key == self.config.shortcuts.get('reset_zoom_key', '').lower():
                self.reset_zoom()
            
            # Handle Control key combinations
            if event.state & 4:  # Control key is pressed
                if key == self.config.shortcuts.get('toggle_sci_ref_key', '').split('-')[-1].lower():
                    self.toggle_sci_ref_var()

        # Bind keyboard events to the shortcut handler
        self.master.bind('<Key>', handle_shortcut)

    def _update_progress_stats(self) -> dict:
        """Calculate progress statistics. Separated from UI updates."""
        try:
            stats = {}
            total_classified = 0
            total_images = len(self.data_manager.region_df)
            
            # Calculate statistics for each tile
            for tile_id in self.config.tile_ids:
                tile_data = self.data_manager.region_df[
                    self.data_manager.region_df['tile_id'] == tile_id
                ]
                classified = tile_data[self.config.classification_labels].any(axis=1).sum()
                total = len(tile_data)
                stats[tile_id] = {
                    'classified': classified,
                    'total': total,
                    'percent': (classified / total * 100) if total > 0 else 0
                }
                total_classified += classified
                
            return {
                'tile_stats': stats,
                'total_classified': total_classified,
                'total_images': total_images,
                'overall_progress': (total_classified / total_images * 100) if total_images > 0 else 0
            }
            
        except Exception as e:
            logging.error(f"Error calculating progress stats: {e}")
            raise

    def update_progress(self):
        """Update progress information with enhanced statistics by tile_id."""
        try:
            # Get statistics
            stats = self._update_progress_stats()
            
            # Update progress bar
            self.progress_var.set(int(stats['overall_progress']))
            
            # Update status text
            status_text = (f"Total Progress: {stats['overall_progress']:.1f}% "
                          f"({stats['total_classified']}/{stats['total_images']})\n")
                          
            for tile_id, tile_stat in stats['tile_stats'].items():
                if tile_stat['total'] > 0:  # Only show tiles that have images
                    status_text += (f"{tile_id}: {tile_stat['classified']}/"
                                  f"{tile_stat['total']} ({tile_stat['percent']:.1f}%)\n")
            
            # Update the status text widget
            if hasattr(self, 'status_text'):
                self.status_text.config(state='normal')
                self.status_text.delete('1.0', 'end')
                self.status_text.insert('1.0', status_text)
                self.status_text.config(state='disabled')
            
        except Exception as e:
            logging.error(f"Error updating progress: {e}")
            raise

    @handle_exceptions
    def display_images(self):
        """
        Display current set of images with proper scaling and normalization.
        
        Loads and displays the current image set (subtracted, science, reference)
        with appropriate scaling and normalization settings. Updates all UI elements
        including zoom, labels, and progress indicators.
        
        Raises:
            ValueError: If image data is invalid
            IndexError: If current index is out of bounds
        """
        try:
            for ax in self.axes:
                ax.clear()

            if self.index >= len(self.data_manager.region_df):
                logging.error(f"Invalid index: {self.index}")
                return
                
            current_row = self.data_manager.region_df.iloc[self.index]
            tile_id = current_row['tile_id']
            unique_number = current_row['unique_number']
            
            if pd.isna(tile_id) or pd.isna(unique_number):
                logging.error(f"Invalid tile_id or unique_number at index {self.index}")
                return

            # Load image data
            sub_data, new_data, ref_data = self.data_manager.load_image_data(self.index)
            
            # Set up the figure title
            self.fig.suptitle(f"Tile ID: {tile_id} - Unique Number: {unique_number}", 
                        fontsize=14, fontweight='bold')

            # Update scale labels
            self.update_scale_labels()

            # Display science image
            if new_data is not None:
                # Prepare normalization once for FITS
                if self.config.file_type == 'fits':
                    sci_norm = self.image_processor.prepare_normalization(new_data,
                                        self.config.vmin_science,
                                        self.config.vmax_science)
                    img_args = {'norm': sci_norm, 'origin': 'lower'}
                else:  # PNG case
                    img_args = {'origin': 'lower'}
                    
                self.axes[0].imshow(new_data, **img_args)
                self.axes[0].set_title("Science Image")

            # Display subtracted image
            if sub_data is not None:
                # Prepare normalization once for FITS
                if self.config.file_type == 'fits':
                    norm = self.image_processor.prepare_normalization(sub_data,
                                        self.config.vmin_subtracted,
                                        self.config.vmax_subtracted)
                    img_args = {'norm': norm, 'origin': 'lower'}
                else:  # PNG case
                    img_args = {'origin': 'lower'}
                    
                self.axes[1].imshow(sub_data, **img_args)
                self.axes[1].set_title("Subtracted Image")

            # Display reference image if enabled
            if self.sci_ref_visible and ref_data is not None:
                # Prepare normalization once for FITS
                if self.config.file_type == 'fits':
                    ref_norm = self.image_processor.prepare_normalization(ref_data,
                                        self.config.vmin_reference,
                                        self.config.vmax_reference)
                    img_args = {'norm': ref_norm, 'origin': 'lower'}
                else:  # PNG case
                    img_args = {'origin': 'lower'}

                self.axes[2].imshow(ref_data, **img_args)
                self.axes[2].set_title("Reference Image")

            # Remove ticks from all axes
            for ax in self.axes:
                ax.set_xticks([])
                ax.set_yticks([])

            # Update zoom parameters when new image is loaded
            if sub_data is not None:
                self.original_size = [sub_data.shape[1], sub_data.shape[0]]
                self.zoom_center = [self.original_size[0]/2, self.original_size[1]/2]
                self.view_size = [size/self.zoom_level for size in self.original_size]

            # Update zoom at the end
            self.update_zoom()

            # Update the canvas
            self.canvas.draw()
            
            # Update progress
            self.update_progress()
            
            # Load memo for current image
            self.load_memo(unique_number)
            
        except Exception as e:
            logging.error(f"Error in display_images: {e}")

    def update_zoom(self):
        """Update the display with current zoom level."""
        if not hasattr(self, 'zoom_level'):
            self.zoom_level = self.config.initial_zoom
            
        for ax in self.axes:
            ax.set_xlim(self.zoom_center[0] - self.view_size[0]/2, 
                        self.zoom_center[0] + self.view_size[0]/2)
            ax.set_ylim(self.zoom_center[1] - self.view_size[1]/2, 
                        self.zoom_center[1] + self.view_size[1]/2)
        
        self.canvas.draw_idle()
            
    def zoom_in(self):
        """Zoom in on the images."""
        try:
            new_zoom = min(self.zoom_level * (1 + self.config.zoom_step), 
                          self.config.zoom_max)
            if new_zoom != self.zoom_level:
                self.zoom_level = new_zoom
                self.view_size = [size/self.zoom_level for size in self.original_size]
                self.update_zoom()
                # Update slider value without triggering callback
                self.zoom_slider.set_val(new_zoom)
                logging.debug(f"Zoomed in to {new_zoom}x")
        except Exception as e:
            logging.error(f"Error in zoom_in: {e}")

    def zoom_out(self):
        """Zoom out from the images."""
        try:
            new_zoom = max(self.zoom_level / (1 + self.config.zoom_step), 
                          self.config.zoom_min)
            if new_zoom != self.zoom_level:
                self.zoom_level = new_zoom
                self.view_size = [size/self.zoom_level for size in self.original_size]
                self.update_zoom()
                # Update slider value without triggering callback
                self.zoom_slider.set_val(new_zoom)
                logging.debug(f"Zoomed out to {new_zoom}x")
        except Exception as e:
            logging.error(f"Error in zoom_out: {e}")

    def reset_zoom(self):
        """Reset zoom to initial value."""
        try:
            self.zoom_level = self.config.initial_zoom
            self.view_size = [size/self.zoom_level for size in self.original_size]
            self.update_zoom()
            # Update slider value without triggering callback
            self.zoom_slider.set_val(self.config.initial_zoom)
            logging.debug("Zoom reset to initial value")
        except Exception as e:
            logging.error(f"Error resetting zoom: {e}")

    @handle_exceptions
    def update_scale_labels(self):
        """Update the scale, vmin, vmax labels with current settings."""
        try:
            # Get current data statistics
            sub_data, new_data, ref_data = self.data_manager.load_image_data(self.index)
            
            if self.config.file_type == 'fits':
                # Update labels for FITS files
                if sub_data is not None:
                    vmin = np.min(sub_data) if self.config.vmin_subtracted == 'min' else np.median(sub_data)
                    vmax = np.max(sub_data) if self.config.vmax_subtracted == 'max' else np.median(sub_data)
                    self.scale_sub_label.config(text=f"Subtracted Image - Scale: {self.config.scale}")
                    self.vmin_sub_label.config(text=f"Vmin: {vmin:.2f}")
                    self.vmax_sub_label.config(text=f"Vmax: {vmax:.2f}")

                if new_data is not None:
                    vmin = np.min(new_data) if self.config.vmin_science == 'min' else np.median(new_data)
                    vmax = np.max(new_data) if self.config.vmax_science == 'max' else np.median(new_data)
                    self.scale_sci_label.config(text=f"Science Image - Scale: {self.config.scale}")
                    self.vmin_sci_label.config(text=f"Vmin: {vmin:.2f}")
                    self.vmax_sci_label.config(text=f"Vmax: {vmax:.2f}")

                if ref_data is not None:
                    vmin = np.min(ref_data) if self.config.vmin_reference == 'min' else np.median(ref_data)
                    vmax = np.max(ref_data) if self.config.vmax_reference == 'max' else np.median(ref_data)
                    self.scale_ref_label.config(text=f"Reference Image - Scale: {self.config.scale}")
                    self.vmin_ref_label.config(text=f"Vmin: {vmin:.2f}")
                    self.vmax_ref_label.config(text=f"Vmax: {vmax:.2f}")
            else:
                # Simple labels for PNG files
                self.scale_sub_label.config(text="Subtracted Image - Scale: PNG")
                self.vmin_sub_label.config(text="")
                self.vmax_sub_label.config(text="")
                self.scale_sci_label.config(text="Science Image - Scale: PNG")
                self.vmin_sci_label.config(text="")
                self.vmax_sci_label.config(text="")
                self.scale_ref_label.config(text="Reference Image - Scale: PNG")
                self.vmin_ref_label.config(text="")
                self.vmax_ref_label.config(text="")
                
        except Exception as e:
            logging.error(f"Error updating scale labels: {e}")

    @handle_exceptions
    def load_memo(self, unique_number: int):
        """Load and display memo for the current image."""
        try:
            current_row = self.data_manager.region_df.iloc[self.index]
            memo = current_row.get('Memo', '').strip()
            self.memo_text.config(state='normal')
            self.memo_text.delete('1.0', 'end')
            self.memo_text.insert('end', memo)
            self.memo_text.config(state='disabled')
        except Exception as e:
            logging.error(f"Error loading memo: {e}")

    def toggle_sci_ref_var(self):
        """
        Toggle the Sci & Ref IntVar value.
        """
        current = self.sci_ref_var.get()
        self.sci_ref_var.set(0 if current else 1)
        logging.debug(f"toggle_sci_ref_var called. Sci & Ref visibility set to {bool(self.sci_ref_var.get())}")
        self.toggle_sci_ref_image()

    @handle_exceptions
    def toggle_sci_ref_image(self):
        """
        Toggle the visibility of science and reference images.
        """
        self.sci_ref_visible = bool(self.sci_ref_var.get())
        self.science_data = None
        self.reference_data = None
        self.display_images()
        logging.info(f"Sci & Ref images visibility set to {self.sci_ref_visible}.")

    @handle_exceptions
    def next_image(self):
        """
        Navigate to the next image, ensuring current image is classified.
        """
        try:
            # Get current unique number from DataFrame
            current_row = self.data_manager.region_df.iloc[self.index]
            unique_number = current_row['unique_number']
            
            # Check if current image is classified
            if not self.is_classified(unique_number) and not self.config.view_mode:
                response = messagebox.askyesno(
                    "Unclassified Image",
                    "The current image has not been classified. Do you want to proceed to the next image?"
                )
                if not response:
                    logging.info("User chose not to navigate to the next image without classification.")
                    return

            if self.index < self.num_images - 1:
                self.index += 1
                self.science_data = None
                self.reference_data = None
                self.display_images()
            else:
                messagebox.showinfo("Info", "You have reached the last image.")
                logging.info("Reached the last image.")
                
        except Exception as e:
            logging.error(f"Error in next_image: {e}")
            raise

    @handle_exceptions
    def prev_image(self):
        """
        Navigate to the previous image.
        """
        if self.index > 0:
            self.index -= 1
            self.science_data = None
            self.reference_data = None
            self.display_images()
        else:
            messagebox.showinfo("Info", "You are at the first image.")
            logging.info("At the first image.")

    @handle_exceptions
    def save_classification(self, classification: str, value: int = 1):
        """Save classification and move to next image."""
        if self.config.view_mode:
            messagebox.showinfo("View Mode", "Classification is disabled in View Mode")
            return

        try:
            current_row = self.data_manager.region_df.iloc[self.index]
            
            # Reset all classification columns to 0 first
            for label in self.config.classification_labels:
                self.data_manager.region_df.at[self.index, label] = 0
                
            # Set the classification value to 1 for the clicked label
            self.data_manager.region_df.at[self.index, classification] = value
            
            # Update metadata
            memo_text = self.memo_text.get('1.0', 'end').strip()
            # Convert empty string to '' instead of NaN
            memo_value = '' if not memo_text else memo_text
            self.data_manager.region_df.at[self.index, 'Memo'] = memo_value
            self.data_manager.region_df.at[self.index, 'Scale'] = self.config.scale
            
            # Save DataFrame immediately
            self.data_manager.save_dataframe(callback=self.after_classification_save)
            
            # Log the save
            tile_id = current_row['tile_id']
            unique_number = current_row['unique_number']
            logging.info(f"Saved classification '{classification}' for Tile: {tile_id}, "
                        f"Number: {unique_number}, Index: {self.index}")
            
        except Exception as e:
            logging.error(f"Error in save_classification: {e}")
            messagebox.showerror("Error", f"Failed to save classification: {e}")

    def after_classification_save(self):
        """Called after classification is saved successfully."""
        self.hide_saving_indicator()
        self.update_progress()
        self.next_image()

    def hide_saving_indicator(self):
        """Hide the saving in progress indicator."""
        # Re-enable classification buttons
        for button in self.classification_buttons.values():
            button.config(state='normal')
        
        # Clear saving status
        if hasattr(self, 'status_text'):
            self.status_text.config(state='normal')
            self.status_text.delete('1.0', 'end')
            self.status_text.config(state='disabled')

    def is_classified(self, unique_number: int) -> bool:
        """
        Check if an image has been classified.

        Parameters:
            unique_number (int): The unique number of the image.

        Returns:
            bool: True if the image is classified, False otherwise.
        """
        try:
            # Get current row from DataFrame
            current_row = self.data_manager.region_df.iloc[self.index]
            
            # Check if any classification column has value 1
            return any(current_row[col] == 1 for col in self.config.classification_labels)
            
        except Exception as e:
            logging.error(f"Error checking classification status: {e}")
            return False

    def init_mode_settings(self):
        """Initialize mode-specific settings based on config"""
        if self.config.specific_view_mode:
            # Specific view mode
            self.title = f"Transient Tool - {self.config.specific_view_mode} View Mode"
            logging.info(f"Initializing in specific view mode: {self.config.specific_view_mode}")
            self.filter_specific_images()
            
        elif self.config.view_mode:
            # View Mode
            self.title = "Transient Tool - View Mode"
            logging.info("Initializing in view mode")

        else:
            # Normal Mode
            self.title = "Transient Tool"
            logging.info("Initializing in normal mode")
            
        self.master.title(self.title)
        
    def filter_specific_images(self):
        """Filter images based on specific view mode"""
        if self.config.specific_view_mode and hasattr(self.data_manager, 'region_df'):
            # Get images where the specified column has value 1
            filtered_df = self.data_manager.region_df[
                self.data_manager.region_df[self.config.specific_view_mode] == 1
            ]
            
            if filtered_df.empty:
                messagebox.showwarning("Warning", 
                    f"No images found with classification '{self.config.specific_view_mode}'")
                # Reset to normal mode if no matching images found
                self.config.specific_view_mode = None
                self.title = "Transient Tool"
                self.master.title(self.title)
                return
                
            # Update data manager with filtered dataframe
            self.data_manager.region_df = filtered_df
            self.num_images = len(filtered_df)
            self.index = 0  # Reset index to start
            
            logging.info(f"Filtered to {self.num_images} images with classification "
                        f"'{self.config.specific_view_mode}'")
            
    def goto_tile_id(self):
        """Jump to the first image of the selected tile ID."""
        try:
            selected_tile = self.tile_combobox.get()
            if not selected_tile:
                messagebox.showwarning("Warning", "Please select a tile ID")
                return
                
            # Find first image with selected tile ID
            tile_images = self.data_manager.region_df[
                self.data_manager.region_df['tile_id'] == selected_tile
            ]
            
            if tile_images.empty:
                messagebox.showwarning("Warning", f"No images found for tile {selected_tile}")
                return
                
            # Get the index of the first image for this tile
            first_tile_index = tile_images.index[0]
            
            # Update display
            self.index = first_tile_index
            self.science_data = None
            self.reference_data = None
            self.display_images()
            
            logging.info(f"Jumped to first image of tile {selected_tile} at index {first_tile_index}")
            
        except Exception as e:
            logging.error(f"Error jumping to tile ID: {e}")
            messagebox.showerror("Error", f"Failed to jump to tile: {e}")
   
    def goto_unique_number(self):
        """Jump to the image with the specified unique number."""
        try:
            unique_num = int(self.unique_entry.get())
            
            # Find the image with this unique number
            matching_images = self.data_manager.region_df[
                self.data_manager.region_df['unique_number'] == unique_num
            ]
            
            if matching_images.empty:
                messagebox.showwarning("Warning", f"No image found with unique number {unique_num}")
                return
                
            # Get the index of the matching image
            target_index = matching_images.index[0]
            
            # Update display
            self.index = target_index
            self.science_data = None
            self.reference_data = None
            self.display_images()
            
            logging.info(f"Jumped to image with unique number {unique_num} at index {target_index}")
            
            # Clear the entry box after successful jump
            self.unique_entry.delete(0, 'end')
            
        except ValueError:
            messagebox.showerror("Error", "Please enter a valid number")
        except Exception as e:
            logging.error(f"Error jumping to unique number: {e}")
            messagebox.showerror("Error", f"Failed to jump to unique number: {e}")

def main():
    """
    Main function to run the TransientTool application.
    """
    # Initialize the root before loading the configuration to ensure logging works
    root = Tk()
    try:
        config = Config.load_config()
    except Exception as e:
        # Set up basic logging before config is loaded
        logging.basicConfig(
            filename='transient_tool.log',
            level=logging.ERROR,
            format='%(asctime)s - %(levelname)s - %(message)s'
        )
        logging.exception("Failed to load configuration.")
        messagebox.showerror("Configuration Error", f"Failed to load configuration: {e}")
        root.quit()
        return

    app = TransientTool(root, config)
    root.mainloop()



if __name__ == "__main__":
    main()
