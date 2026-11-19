package com.conto.notificacoes;

import android.app.Activity;
import android.app.NotificationManager;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.ApplicationInfo;
import android.content.pm.PackageManager;
import android.os.Build;
import android.provider.Settings;

import com.google.appinventor.components.annotations.DesignerComponent;
import com.google.appinventor.components.annotations.DesignerProperty;
import com.google.appinventor.components.annotations.PropertyCategory;
import com.google.appinventor.components.annotations.SimpleEvent;
import com.google.appinventor.components.annotations.SimpleFunction;
import com.google.appinventor.components.annotations.SimpleObject;
import com.google.appinventor.components.annotations.SimpleProperty;
import com.google.appinventor.components.annotations.UsesServices;
import com.google.appinventor.components.annotations.androidmanifest.ActionElement;
import com.google.appinventor.components.annotations.androidmanifest.IntentFilterElement;
import com.google.appinventor.components.annotations.androidmanifest.ServiceElement;
import com.google.appinventor.components.common.ComponentCategory;
import com.google.appinventor.components.common.PropertyTypeConstants;
import com.google.appinventor.components.runtime.AndroidNonvisibleComponent;
import com.google.appinventor.components.runtime.ComponentContainer;
import com.google.appinventor.components.runtime.EventDispatcher;
import com.google.appinventor.components.runtime.OnDestroyListener;
import com.google.appinventor.components.runtime.util.YailList;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.List;

/**
 * Leitor de notificações para o Contô.
 *
 * Um NotificationListenerService (ServicoNotificacoes) guarda, mesmo com o app fechado, as notificações dos apps
 * monitorados (apps de banco). Este componente deixa os blocos lerem essas notificações guardadas, apagar as já
 * tratadas e abrir a tela do Android onde a pessoa libera o "Acesso a notificações".
 */
@DesignerComponent(version = 1,
    androidMinSdk = 21,
    versionName = "1.1",
    description = "Lê as notificações dos apps de banco (com o \"Acesso a notificações\" liberado) e guarda-as "
        + "para o app tratar depois, mesmo com o app fechado.",
    category = ComponentCategory.EXTENSION,
    nonVisible = true,
    iconName = "images/extension.png")
@SimpleObject(external = true)
@UsesServices(services = {
    @ServiceElement(name = "com.conto.notificacoes.ServicoNotificacoes",
        permission = "android.permission.BIND_NOTIFICATION_LISTENER_SERVICE",
        exported = "true",
        intentFilters = {
            @IntentFilterElement(actionElements = {
                @ActionElement(name = "android.service.notification.NotificationListenerService")
            })
        })
})
public class LeitorNotificacoes extends AndroidNonvisibleComponent implements OnDestroyListener {

  private final Activity activity;

  public LeitorNotificacoes(ComponentContainer container) {
    super(container.$form());
    activity = container.$context();
    Armazem.componenteAtivo = this;
    form.registerForOnDestroy(this);
  }

  @Override
  public void onDestroy() {
    if (Armazem.componenteAtivo == this) {
      Armazem.componenteAtivo = null;
    }
  }

  // ------------------------------------------------------------------ propriedades

  @DesignerProperty(editorType = PropertyTypeConstants.PROPERTY_TYPE_TEXTAREA, defaultValue = Armazem.APPS_PADRAO)
  @SimpleProperty(category = PropertyCategory.BEHAVIOR, description = "Pacotes dos apps cujas notificações são guardadas, separados por vírgula "
      + "(ex.: com.nu.production). Vazio = todos os apps (menos o próprio).")
  public void AppsMonitorados(String pacotes) {
    Armazem.prefs(activity).edit().putString(Armazem.CHAVE_APPS, pacotes == null ? "" : pacotes.trim()).apply();
  }

  @DesignerProperty(editorType = PropertyTypeConstants.PROPERTY_TYPE_BOOLEAN, defaultValue = "True")
  @SimpleProperty(category = PropertyCategory.BEHAVIOR, description = "Guardar só notificações com valor em dinheiro (R$, BRL ou reais).")
  public void ApenasComValor(boolean sim) {
    Armazem.prefs(activity).edit().putBoolean(Armazem.CHAVE_SO_VALOR, sim).apply();
  }

  @SimpleProperty(category = PropertyCategory.BEHAVIOR)
  public boolean ApenasComValor() {
    return Armazem.soComValor(activity);
  }

  @SimpleProperty(category = PropertyCategory.BEHAVIOR)
  public String AppsMonitorados() {
    return Armazem.prefs(activity).getString(Armazem.CHAVE_APPS, Armazem.APPS_PADRAO);
  }

  @DesignerProperty(editorType = PropertyTypeConstants.PROPERTY_TYPE_TEXTAREA, defaultValue = Regras.IGNORADOS_PADRAO)
  @SimpleProperty(category = PropertyCategory.BEHAVIOR, description = "Pacotes de apps cujas notificações nunca são "
      + "guardadas (conversas e e-mail), separados por vírgula.")
  public void AppsIgnorados(String pacotes) {
    Armazem.prefs(activity).edit().putString(Armazem.CHAVE_IGNORADOS, pacotes == null ? "" : pacotes.trim()).apply();
  }

  @SimpleProperty(category = PropertyCategory.BEHAVIOR)
  public String AppsIgnorados() {
    return Armazem.prefs(activity).getString(Armazem.CHAVE_IGNORADOS, Regras.IGNORADOS_PADRAO);
  }

  // ------------------------------------------------------------------ funções

  @SimpleFunction(description = "Verdadeiro se a pessoa já liberou o \"Acesso a notificações\" para este app.")
  public boolean AcessoLiberado() {
    ComponentName componente = new ComponentName(activity, ServicoNotificacoes.class);
    if (Build.VERSION.SDK_INT >= 27) {
      // caminho oficial (Android 8.1+): nao depende de ler uma configuracao escondida do sistema
      try {
        NotificationManager nm = (NotificationManager) activity.getSystemService(Context.NOTIFICATION_SERVICE);
        if (nm != null) {
          return nm.isNotificationListenerAccessGranted(componente);
        }
      } catch (Throwable ignorada) {
        // cai para a leitura da configuracao abaixo
      }
    }
    try {
      String lista = Settings.Secure.getString(activity.getContentResolver(), "enabled_notification_listeners");
      if (lista == null) {
        return false;
      }
      String meu = componente.flattenToString();
      for (String item : lista.split(":")) {
        if (item.equals(meu) || item.startsWith(activity.getPackageName() + "/")) {
          return true;
        }
      }
      return false;
    } catch (Throwable t) {
      return false;      // nunca derruba o app por causa da consulta; as notificacoes guardadas aparecem do mesmo jeito
    }
  }

  @SimpleFunction(description = "Abre a tela do Android onde a pessoa libera o \"Acesso a notificações\".")
  public void AbrirConfiguracaoDeAcesso() {
    Intent intent;
    if (Build.VERSION.SDK_INT >= 30) {
      intent = new Intent("android.settings.NOTIFICATION_LISTENER_DETAIL_SETTINGS");
      intent.putExtra("android.provider.extra.NOTIFICATION_LISTENER_COMPONENT_NAME",
          new ComponentName(activity, ServicoNotificacoes.class).flattenToString());
      if (intent.resolveActivity(activity.getPackageManager()) == null) {
        intent = new Intent("android.settings.ACTION_NOTIFICATION_LISTENER_SETTINGS");
      }
    } else {
      intent = new Intent("android.settings.ACTION_NOTIFICATION_LISTENER_SETTINGS");
    }
    intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
    try {
      activity.startActivity(intent);
    } catch (Exception e) {
      try {
        Intent geral = new Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS);
        geral.setData(android.net.Uri.parse("package:" + activity.getPackageName()));
        geral.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        activity.startActivity(geral);
      } catch (Exception ignorada) {
        Erro("Não foi possível abrir as configurações: " + e.getMessage());
      }
    }
  }

  @SimpleFunction(description = "Verdadeiro se o Android está com o leitor ligado agora (alguns celulares desligam o "
      + "leitor quando o app vai para o fundo).")
  public boolean LeitorConectado() {
    return AcessoLiberado() && Armazem.prefs(activity).getBoolean(Armazem.CHAVE_CONECTADO, false);
  }

  @SimpleFunction(description = "Pede ao Android para religar o leitor de notificações (com o acesso liberado). Ao "
      + "religar, o leitor relê as notificações que ainda estão na barra.")
  public void Reconectar() {
    if (!AcessoLiberado()) {
      return;
    }
    ComponentName componente = new ComponentName(activity, ServicoNotificacoes.class);
    try {
      // desligar e ligar o componente do servico faz o Android desfazer e refazer a ligacao com o leitor
      PackageManager pm = activity.getPackageManager();
      pm.setComponentEnabledSetting(componente, PackageManager.COMPONENT_ENABLED_STATE_DISABLED,
          PackageManager.DONT_KILL_APP);
      pm.setComponentEnabledSetting(componente, PackageManager.COMPONENT_ENABLED_STATE_ENABLED,
          PackageManager.DONT_KILL_APP);
    } catch (Throwable t) {
      // segue para o pedido oficial abaixo
    }
    try {
      if (Build.VERSION.SDK_INT >= 24) {
        android.service.notification.NotificationListenerService.requestRebind(componente);
      }
    } catch (Throwable t) {
      Erro("Não foi possível religar o leitor de notificações: " + t.getMessage());
    }
  }

  @SimpleFunction(description = "Texto curto dizendo se o leitor está ligado, quantas notificações ele já viu e o "
      + "que aconteceu com a última (guardada, sem valor em R$, app ignorado...).")
  public String Diagnostico() {
    SharedPreferences p = Armazem.prefs(activity);
    String app = p.getString(Armazem.CHAVE_ULT_APP, "");
    String hora = "";
    long quando = p.getLong(Armazem.CHAVE_ULT_QUANDO, 0);
    if (quando > 0) {
      hora = new java.text.SimpleDateFormat("dd/MM HH:mm", java.util.Locale.getDefault()).format(new java.util.Date(quando));
    }
    return Regras.diagnostico(AcessoLiberado(), LeitorConectado(), p.getLong(Armazem.CHAVE_VISTAS, 0),
        app.length() == 0 ? "" : NomeDoApp(app), p.getString(Armazem.CHAVE_ULT_MOTIVO, ""), hora);
  }

  @SimpleFunction(description = "Abre a tela \"Informações do app\" (no Android 13+ é ali, no menu de 3 pontos, "
      + "que fica \"Permitir configurações restritas\").")
  public void AbrirInformacoesDoApp() {
    try {
      Intent intent = new Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS);
      intent.setData(android.net.Uri.parse("package:" + activity.getPackageName()));
      intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
      activity.startActivity(intent);
    } catch (Exception e) {
      Erro("Não foi possível abrir as informações do app: " + e.getMessage());
    }
  }

  @SimpleFunction(description = "Notificações guardadas e ainda não apagadas, da mais antiga para a mais nova. "
      + "Cada item é uma lista: id, pacote do app, nome do app, título, texto, quando (milissegundos).")
  public YailList Pendentes() {
    List<YailList> itens = new ArrayList<YailList>();
    JSONArray arr = Armazem.ler(activity);
    for (int i = 0; i < arr.length(); i++) {
      JSONObject o = arr.optJSONObject(i);
      if (o == null) {
        continue;
      }
      List<Object> item = new ArrayList<Object>();
      item.add(o.optString("id"));
      item.add(o.optString("app"));
      item.add(NomeDoApp(o.optString("app")));
      item.add(o.optString("titulo"));
      item.add(o.optString("texto"));
      item.add(String.valueOf(o.optLong("quando")));
      itens.add(YailList.makeList(item));
    }
    return YailList.makeList(itens);
  }

  @SimpleFunction(description = "Quantas notificações estão guardadas.")
  public int QuantidadePendente() {
    return Armazem.ler(activity).length();
  }

  @SimpleFunction(description = "Apaga a notificação guardada com esse id (depois de tratada).")
  public void Remover(String id) {
    Armazem.remover(activity, id);
  }

  @SimpleFunction(description = "Apaga todas as notificações guardadas.")
  public void LimparTudo() {
    Armazem.limpar(activity);
  }

  @SimpleFunction(description = "Nome que aparece para o app com esse pacote (ex.: com.nu.production -> Nubank).")
  public String NomeDoApp(String pacote) {
    try {
      PackageManager pm = activity.getPackageManager();
      ApplicationInfo info = pm.getApplicationInfo(pacote, 0);
      CharSequence nome = pm.getApplicationLabel(info);
      if (nome != null && nome.length() > 0) {
        return nome.toString();
      }
    } catch (Exception ignorada) {
      // app não instalado ou sem permissão para ver (Android 11+): usa a lista conhecida
    }
    return Armazem.nomeConhecido(pacote);
  }

  // ------------------------------------------------------------------ eventos

  @SimpleEvent(description = "Chegou uma notificação de um app monitorado (só dispara com o app aberto; ela "
      + "também fica guardada em Pendentes).")
  public void NotificacaoRecebida(String id, String app, String nomeDoApp, String titulo, String texto) {
    EventDispatcher.dispatchEvent(this, "NotificacaoRecebida", id, app, nomeDoApp, titulo, texto);
  }

  @SimpleEvent(description = "Algo deu errado no leitor de notificações.")
  public void Erro(String mensagem) {
    EventDispatcher.dispatchEvent(this, "Erro", mensagem);
  }

  /** Chamado pelo serviço (thread qualquer) quando guarda uma notificação nova. */
  void avisar(final String id, final String app, final String titulo, final String texto) {
    activity.runOnUiThread(new Runnable() {
      @Override
      public void run() {
        NotificacaoRecebida(id, app, NomeDoApp(app), titulo, texto);
      }
    });
  }
}
