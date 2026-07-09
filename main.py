import json
import os
import requests
from io import BytesIO
from PIL import Image
import numpy as np
from kivy.app import App
from kivy.clock import mainthread
from kivy.core.text import LabelBase
from kivy.core.window import Window
from kivy.lang import Builder
from kivy.properties import StringProperty, ListProperty, DictProperty, ObjectProperty
from kivy.uix.image import Image as KivyImage
from kivy.uix.screenmanager import ScreenManager, Screen
from kivy.uix.popup import Popup
from kivy.uix.label import Label
from kivy.uix.filechooser import FileChooserIconView
from kivy.uix.button import Button
import tkinter as tk
from tkinter import filedialog
import platform
from kivy.config import Config
from tensorflow.lite.python.interpreter import Interpreter
from kivy.properties import StringProperty
from kivy.uix.togglebutton import ToggleButton
from kivy.uix.popup import Popup
from kivy.uix.filechooser import FileChooserIconView
from plyer import filechooser


class CircleToggleButton(ToggleButton):
    icon_source = StringProperty('')
    text = StringProperty('')
    
LabelBase.register(name="EnglishFont", fn_regular="assets/fonts/NotoSans-Regular.ttf")
LabelBase.register(name="HindiFont", fn_regular="assets/fonts/NotoSansDevanagari-Regular.ttf")

KV_FILE = "smartfarm.kv"
if os.path.exists(KV_FILE):
    Builder.load_file(KV_FILE)
else:
    Builder.load_string('''
<HomeScreen>:
    BoxLayout:
        orientation: 'vertical'
        Label:
            text: app.strings['title']
            font_name: app.current_font
            font_size: '32sp'
        Button:
            text: 'Go to Crop Select'
            on_release: app.goto('crop_select')

<CropSelectScreen>:
    BoxLayout:
        orientation: 'vertical'
        GridLayout:
            id: crop_grid
            cols: 2
        Button:
            id: btn_next
            text: 'Next'
            disabled: True
            on_release: app.goto('dashboard')

<DashboardScreen>:
    BoxLayout:
        orientation: 'vertical'
        Label:
            text: root.app.weather_text
            font_name: root.app.current_font
        Button:
            text: 'Take Photo'
            on_release: root.app.take_photo()
        Button:
            text: 'Upload Photo'
            on_release: root.show_file_chooser()

<DiagnosisScreen>:
    BoxLayout:
        orientation: 'vertical'
        Label:
            id: disease_name_label
            text: 'Disease:'
            font_name: app.current_font
            font_size: '20sp'
        Label:
            id: treatment_label
            text: 'Treatment:'
            font_name: app.current_font
            font_size: '16sp'
        Button:
            text: 'Back Home'
            on_release: app.goto('home')
''')

class HomeScreen(Screen):
    pass

class CropSelectScreen(Screen):
    max_selection = 8

    def on_pre_enter(self):
        self.app.selected_crops.clear()
        self.ids.btn_next.disabled = True
        self.ids.crop_grid.clear_widgets()

        # Example crop list with icon filenames
        crops = [
            {"name": "Wheat", "icon": "assets/wheat.png"},
            {"name": "Corn", "icon": "assets/corn.png"},
            {"name": "Rice", "icon": "assets/rice.png"},
            {"name": "Leaf", "icon": "assets/leaf.png"},
            {"name": "Tomato", "icon": "assets/Tomato.png"},
            {"name": "Potato", "icon": "assets/Potato.png"},
            {"name": "Peppper Bell", "icon": "assets/pb.png"},
            {"name": "Sugar Cane", "icon": "assets/sg.png"},
        ]

        for crop in crops:
            btn = CircleToggleButton(
                icon_source=crop["icon"],
                text=crop["name"],
                group="crops"
            )
            btn.bind(on_release=lambda btn_instance, crop_name=crop["name"]: self.on_crop_toggle(crop_name, btn_instance))
            self.ids.crop_grid.add_widget(btn)

    def on_crop_toggle(self, crop_name, toggle_button):
        if toggle_button.state == 'down':
            if len(self.app.selected_crops) >= self.max_selection:
                toggle_button.state = 'normal'
                return
            self.app.selected_crops.append(crop_name)
        else:
            if crop_name in self.app.selected_crops:
                self.app.selected_crops.remove(crop_name)
        self.ids.btn_next.disabled = len(self.app.selected_crops) == 0


def open_file_explorer_android(self):
    filechooser.open_file(on_selection=self.selection_callback)

def selection_callback(self, selection):
    if selection:
        self.app.process_image_path(selection[0])

class DashboardScreen(Screen):
    def open_native_file_explorer(self):
        root = tk.Tk()
        root.withdraw()  # Hide the root window
        file_path = filedialog.askopenfilename(title="Select an image",filetypes=[("Image files", "*.png;*.jpg;*.jpeg;*.bmp;*.gif")])
        root.destroy()
        if file_path:
            self.app.process_image_path(file_path)


    def selected(self, filechooser, selection):
        if selection:
            selected_path = selection[0]
            self.popup.dismiss()
            self.app.process_image_path(selected_path)  # Process the selected image


class DiagnosisScreen(Screen):
    def display_result(self, disease_name, treatment):
        self.ids.disease_name_label.text = f"Disease: {disease_name}"
        self.ids.treatment_label.text = f"Treatment: {treatment}"


class SmartFarmApp(App):
    icon = 'assets/appicon.png'
    current_language = StringProperty('English')
    current_language_name = StringProperty('English')
    current_font = StringProperty('EnglishFont')
    available_languages = ListProperty(['English', 'हिंदी'])
    selected_crops = ListProperty([])
    weather_text = StringProperty('Fetching weather...')
    strings = DictProperty()
    model = None
    interpreter = None
    input_index = None
    output_index = None
    class_names = {}
    treatment_dict = {}

    translations_dict = {
        'English': {
            'title': 'SmartFarm',
            'take_photo': 'Take Photo',
            'upload_photo': 'Upload Photo',
            'discard_photo': 'Discard Photo',
            'analysis_placeholder': 'Disease & Cure will appear here',
            'instruction_text': 'Upload or capture a crop image for analysis',
            'tips_header': 'Farming Tips & Suggestions',
        },
        'हिंदी': {
            'title': 'स्मार्टफार्म',
            'take_photo': 'फोटो लें',
            'upload_photo': 'फोटो अपलोड करें',
            'discard_photo': 'फोटो हटाएँ',
            'analysis_placeholder': 'रोग और इलाज यहाँ दिखेगा',
            'instruction_text': 'विश्लेषण के लिए फ़सल की फोटो अपलोड या कैप्चर करें',
            'tips_header': 'खेती सुझाव और सलाह',
        }
    }

    def build(self):
        self.strings = self.translations_dict[self.current_language]
        self.root = ScreenManager()
        self.root.add_widget(HomeScreen(name='home'))
        self.root.add_widget(CropSelectScreen(name='crop_select'))
        self.root.add_widget(DashboardScreen(name='dashboard'))
        self.root.add_widget(DiagnosisScreen(name='diagnosis'))
        self.load_model_and_data()
        self.request_location_permission()
        self.fetch_weather_async()
        return self.root

    def on_start(self):
        for screen in self.root.screens:
            screen.app = self

    def load_model_and_data(self):
        # Load TFLite model
        model_path = os.path.join('assets', 'model.tflite')  # change your model filename here
        if not os.path.exists(model_path):
            print(f"TFLite model not found at {model_path}")
            return
        self.interpreter = Interpreter(model_path=model_path)
        self.interpreter.allocate_tensors()
        input_details = self.interpreter.get_input_details()
        output_details = self.interpreter.get_output_details()
        self.input_index = input_details[0]['index']
        self.output_index = output_details[0]['index']
        print("TFLite model loaded successfully")

        # Load class names JSON
        class_json_path = os.path.join('assets', 'class_names.json')
        if os.path.exists(class_json_path):
            with open(class_json_path, 'r', encoding='utf-8') as f:
                self.class_names = json.load(f)

        # Load treatment JSON
        treatment_json_path = os.path.join('assets', 'treatment_map.json')
        if os.path.exists(treatment_json_path):
            with open(treatment_json_path, 'r', encoding='utf-8') as f:
                self.treatment_dict = json.load(f)

    def request_location_permission(self):
        # Platform-specific location permission logic
        # For now, we print a placeholder
        print("Requesting location permission... (implement as needed)")

    def fetch_weather_async(self):
        from threading import Thread
        Thread(target=self.fetch_weather).start()

    def fetch_weather(self):
        # Placeholder approximate location - replace with actual location retrieval
        lat, lon = 28.6139, 77.2090  # Delhi approximate coords
        api_key = "your_openweathermap_api_key"  # Replace with valid key
        try:
            url = f"http://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={api_key}&units=metric"
            resp = requests.get(url)
            data = resp.json()
            desc = data['weather'][0]['description']
            temp = data['main']['temp']
            weather_str = f"Weather: {desc.capitalize()}, {temp}°C"
            self.update_weather_text(weather_str)
        except Exception as e:
            self.update_weather_text("Weather data unavailable")
            print(f"Weather fetch error: {e}")

    @mainthread
    def update_weather_text(self, text):
        self.weather_text = text

    def set_language(self, lang_name):
        if lang_name in self.translations_dict:
            self.current_language = lang_name
            self.current_language_name = lang_name
            self.current_font = 'HindiFont' if lang_name == 'हिंदी' else 'EnglishFont'
            self.strings = self.translations_dict[lang_name]

    def change_language(self, lang_name):
        self.set_language(lang_name)

    def goto(self, screen_name):
        if screen_name in self.root.screen_names:
            self.root.current = screen_name

    def take_photo(self):
        # Placeholder for taking photo with device camera
        print("Taking photo... (implement camera integration)")

    def process_image_path(self, image_path):
        try:
            img = Image.open(image_path).convert('RGB')
            img = img.resize((224, 224))  # Adjust size as per model's input
            input_data = np.expand_dims(np.array(img) / 255.0, axis=0).astype(np.float32)
            self.interpreter.set_tensor(self.input_index, input_data)
            self.interpreter.invoke()
            output_data = self.interpreter.get_tensor(self.output_index)
            pred_index = np.argmax(output_data[0])
            disease_name = "Unknown"

            if 0 <= pred_index < len(self.class_names):
                disease_name = self.class_names[pred_index]
            normalized_treatments = {k.strip().lower(): v for k, v in self.treatment_dict.items()}
            key = disease_name.strip().lower()
            treatment = normalized_treatments.get(key, "No treatment info available")

            self.show_diagnosis(disease_name, treatment, image_path=image_path)
        except Exception as e:
            print(f"Error processing image: {e}")


    def show_diagnosis(self, disease_name, treatment,image_path= None ):
        self.goto('diagnosis')
        diag_screen = self.root.get_screen('diagnosis')
        diag_screen.display_result(disease_name, treatment)
        if image_path and os.path.exists(image_path):
            diag_screen.ids.plant_image_display.source = image_path
            diag_screen.ids.plant_image_display.reload()
        else:
            diag_screen.ids.plant_image_display.source = ''


if __name__ == '__main__':
    Window.size = (360, 640)
    SmartFarmApp().run()
